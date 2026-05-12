"""
sim_engine.py — Real-time physics simulation engine.

Runs in a dedicated background thread.  The main HTTP thread submits
mutations via SimEngine.mutate() and scheduled events via schedule_event().
The sim thread processes events and emits animation frames at ~100 ms
intervals (configurable via heartbeat_interval_ms).

Frame format
------------
Each frame is a dict: {id, sim_time_ms, nodes: [{id, summary, status}], events: [...]}
  - nodes: subset of devices whose state changed since the last frame
  - events: RELAY_PICKUP, RELAY_DROPOUT, FAULT, CLEAR_FAULT etc.

Event queue
-----------
Events are (trigger_time_ms, seq, event_type, data).  The seq counter
breaks ties so that equal-time events are processed in submission order,
avoiding a TypeError when Python tries to compare the dict payloads.
Types: FAULT, CLEAR_FAULT, TRIP, CLOSE.

Locking
-------
self.lock is an RLock so that schedule_event() can be called safely from
within the sim thread (e.g. from _update_physics) without deadlocking.

Speed multiplier
----------------
Wall-clock time is scaled by speed_multiplier before advancing sim_time_ms.
1.0 = real time, 0.1 = slow motion, 10.0 = fast-forward.
"""

import topology_utils
import threading
import time
import queue
import copy
import uuid
from model_loader import load_substation_model

class SimEngine:
    def __init__(self):
        self.lock = threading.RLock()  # reentrant: schedule_event safe from sim thread
        self.running = False
        self.paused = False
        self.sim_time_ms = 0.0
        self.speed_multiplier = 1.0
        self.last_update_real_time = 0.0

        self.topology_data = None
        self.devices = {}
        self.sources = []

        self.event_queue = queue.PriorityQueue() # (trigger_time_ms, seq, event_type, data)
        self._event_seq = 0  # monotonic counter breaks ties so dict payloads are never compared
        self.frame_buffer = []
        self.next_frame_id = 0
        self.max_buffer_size = 10000
        self._frame_events = []  # notification events collected between frames
        
        self.thread = None
        self.heartbeat_interval_ms = 100.0
        self.last_heartbeat_sim_time = 0.0

    def start(self, topology_data):
        with self.lock:
            if self.running:
                return
            self.topology_data = copy.deepcopy(topology_data)
            self.sources, self.devices, _, _, _ = self._load_model(self.topology_data)
            self.sim_time_ms = 0.0
            self.last_update_real_time = time.time()
            self.running = True
            self.paused = True
            self.frame_buffer = []
            self.next_frame_id = 0
            self._frame_events = []
            self.event_queue = queue.PriorityQueue()
            self._event_seq = 0
            
            # Initial frame
            self._emit_frame(is_snapshot=True)
            
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
            if self.thread:
                # We don't join here to avoid blocking the API thread
                self.thread = None

    def pause(self, paused=True):
        with self.lock:
            self.paused = paused
            if not self.paused:
                self.last_update_real_time = time.time()

    def set_speed(self, multiplier):
        with self.lock:
            self.speed_multiplier = max(0.01, min(100.0, multiplier))

    def schedule_event(self, delay_ms, event_type, data):
        with self.lock:
            trigger_time = self.sim_time_ms + delay_ms
            self.event_queue.put((trigger_time, self._event_seq, event_type, data))
            self._event_seq += 1

    def get_frames(self, since_id):
        with self.lock:
            return [f for f in self.frame_buffer if f["id"] > since_id]

    def _load_model(self, data):
        devices = load_substation_model(data)
        for dev in devices.values():
            dev.is_sim = True
        sources = [dev for dev in devices.values() if getattr(dev, "type", "") == "VoltageSource" or dev.__class__.__name__ == "VoltageSource"]
        return sources, devices, data.get("devices", []), data.get("reference", {}), data.get("project_info", {"station": "", "device": ""})

    def _run(self):
        while True:
            with self.lock:
                if not self.running:
                    break
                if self.paused:
                    time.sleep(0.1)
                    continue
                
                now = time.time()
                real_dt = now - self.last_update_real_time
                self.last_update_real_time = now
                
                sim_dt = real_dt * 1000.0 * self.speed_multiplier
                self.sim_time_ms += sim_dt
                
                # Process events
                self._process_events()
                
                # Run cascade logic (phasor calc + device updates)
                self._update_physics()
                
                # Heartbeat frame if enough time passed
                if self.sim_time_ms - self.last_heartbeat_sim_time >= self.heartbeat_interval_ms:
                    self._emit_frame()
                    self.last_heartbeat_sim_time = self.sim_time_ms
            
            # Control loop frequency
            time.sleep(0.02) # ~50Hz real-time

    def _process_events(self):
        while not self.event_queue.empty():
            trigger_time, _seq, event_type, data = self.event_queue.queue[0]
            if trigger_time <= self.sim_time_ms:
                self.event_queue.get()
                self._handle_event(event_type, data)
            else:
                break

    def _handle_event(self, event_type, data):
        if event_type == "FAULT":
            device_id = data.get("device_id")
            if device_id in self.devices:
                dev = self.devices[device_id]
                if hasattr(dev, "inject_fault"):
                    dev.inject_fault(data)
            self._frame_events.append({"type": "FAULT", "sim_time": self.sim_time_ms, **data})
        elif event_type == "CLEAR_FAULT":
            device_id = data.get("device_id")
            if device_id in self.devices:
                dev = self.devices[device_id]
                if hasattr(dev, "clear_fault"):
                    dev.clear_fault()
            self._frame_events.append({"type": "CLEAR_FAULT", "sim_time": self.sim_time_ms, **data})
        elif event_type == "TOGGLE":
            device_id = data.get("device_id")
            if device_id in self.devices:
                dev = self.devices[device_id]
                if hasattr(dev, "is_closed"):
                    dev.is_closed = not dev.is_closed
                    self._cache_clear_all()
        elif event_type == "TRIP":
            device_id = data.get("device_id")
            phase = data.get("phase", "abc")
            if device_id in self.devices:
                dev = self.devices[device_id]
                if hasattr(dev, "handle_trip_signal"):
                    dev.handle_trip_signal(phase, self.sim_time_ms)
        elif event_type == "CLOSE":
            device_id = data.get("device_id")
            phase = data.get("phase", "abc")
            if device_id in self.devices:
                dev = self.devices[device_id]
                if hasattr(dev, "handle_close_signal"):
                    dev.handle_close_signal(phase, self.sim_time_ms)

    _NOTIFICATION_EVENT_TYPES = {"RELAY_PICKUP", "RELAY_DROPOUT", "SWITCH_OP", "CLEAR_FAULT", "AR_RECLOSE", "AR_LOCKOUT", "BF_TRIP"}

    def _update_physics(self):
        # Force recalculation by clearing all caches
        self._cache_clear_all()

        for dev in self.devices.values():
            if hasattr(dev, "sim_step"):
                events = dev.sim_step(self.sim_time_ms)
                for e in events:
                    if e["type"] in self._NOTIFICATION_EVENT_TYPES:
                        # Log directly — these are notifications, not actions to re-process
                        self._frame_events.append({"type": e["type"], "sim_time": self.sim_time_ms, **e["data"]})
                    else:
                        self.schedule_event(e["delay"], e["type"], e["data"])

    def _emit_frame(self, is_snapshot=False):
        frame = {
            "id": self.next_frame_id,
            "sim_time": self.sim_time_ms,
            "events": list(self._frame_events),
            "changes": {}
        }
        self._frame_events = []
        
        if is_snapshot:
            # Generate full SLD response for structural changes
            import api
            _, _, raw_devices, reference, _ = self._load_model(self.topology_data)
            frame["full_sld"] = api._build_topology_response(
                self.sources, self.devices, raw_devices, reference
            )

        for did, dev in self.devices.items():
            state = self._get_device_state(dev)
            if state:
                frame["changes"][did] = state

        self.frame_buffer.append(frame)
        self.next_frame_id += 1
        if len(self.frame_buffer) > self.max_buffer_size:
            self.frame_buffer.pop(0)

    def _get_device_state(self, dev):
        state = {}
        if hasattr(dev, "is_closed"):
            state["status"] = "CLOSED" if dev.is_closed else "OPEN"
        if hasattr(dev, "_manual_closed"):
            state["manual_closed_phases"] = dev._manual_closed
        if hasattr(dev, "target_dropped"):
            state["target_dropped"] = dev.target_dropped
        state["fault_state"] = getattr(dev, "fault_state", None)
        
        if hasattr(dev, "current") and dev.current:
            state["current"] = {
                "a": {"mag": dev.current.a.magnitude, "ang": dev.current.a.angle_degrees},
                "b": {"mag": dev.current.b.magnitude, "ang": dev.current.b.angle_degrees},
                "c": {"mag": dev.current.c.magnitude, "ang": dev.current.c.angle_degrees},
            }
        
        return state


    def mutate(self, req):
        with self.lock:
            self.topology_data = topology_utils.apply_reconfiguration(self.topology_data, req)
            
            # Re-load model
            new_sources, new_devices, _, _, _ = self._load_model(self.topology_data)
            
            # TRANSFER ANALOG INPUTS (Crucial for cascaded sensors!)
            # When we reload the model, the secondary_connections lists are rebuilt,
            # but we need to ensure the cascaded CTs keep their analog input links.
            # Wait, model_loader.py handles secondary_connections based on topology JSON.
            # So if topology JSON is updated, reload should work.

            # Transfer state (breaker positions, fault states)
            for did, old_dev in self.devices.items():
                if did in new_devices:
                    new_dev = new_devices[did]
                    if hasattr(old_dev, "_manual_closed") and hasattr(new_dev, "_manual_closed"):
                        new_dev._manual_closed = copy.deepcopy(old_dev._manual_closed)
                    if hasattr(old_dev, "fault_state") and hasattr(new_dev, "fault_state"):
                        new_dev.fault_state = old_dev.fault_state
                    if hasattr(old_dev, "_sim_active_outputs") and hasattr(new_dev, "_sim_active_outputs"):
                        new_dev._sim_active_outputs = copy.deepcopy(old_dev._sim_active_outputs)
                    if hasattr(old_dev, "_sim_pickup_timers") and hasattr(new_dev, "_sim_pickup_timers"):
                        new_dev._sim_pickup_timers = copy.deepcopy(old_dev._sim_pickup_timers)
                    if hasattr(old_dev, "_sim_dropout_timers") and hasattr(new_dev, "_sim_dropout_timers"):
                        new_dev._sim_dropout_timers = copy.deepcopy(old_dev._sim_dropout_timers)
                    if hasattr(old_dev, "elements") and hasattr(new_dev, "elements"):
                        for bit_name, old_elem in old_dev.elements.items():
                            if bit_name in new_dev.elements:
                                new_dev.elements[bit_name].copy_state_from(old_elem)
                        if hasattr(old_dev, "_elem_prev_time"):
                            new_dev._elem_prev_time = old_dev._elem_prev_time
                    for attr in ("_ar_state", "_ar_shot_count", "_ar_timer", "_ar_locked_out",
                                 "_bf_timer", "_bf_operated"):
                        if hasattr(old_dev, attr):
                            setattr(new_dev, attr, getattr(old_dev, attr))
            
            self.sources = new_sources
            self.devices = new_devices
            self._emit_frame(is_snapshot=True)

    def update_relay_settings(self, device_id: str, new_settings: dict):
        """Merge new_settings into a running relay's settings dict.

        Because ProtectionElement holds a shared reference to relay.settings,
        numeric/curve changes take effect on the very next sim_step with no
        rebuild needed.  If the new settings introduce element types that don't
        yet exist (e.g. a freshly added 51N1P key), elements are rebuilt and
        existing accumulator state is transferred.
        """
        with self.lock:
            dev = self.devices.get(device_id)
            if dev is None or not hasattr(dev, "elements"):
                return False

            # Merge in-place so element shared-references stay valid
            dev.settings.update(new_settings)

            # Rebuild elements — preserves state for unchanged elements
            from phasors.devices.protection_elements import build_elements_from_settings
            new_elements = {e.bit_name: e for e in build_elements_from_settings(dev.settings)}
            for bit_name, old_elem in dev.elements.items():
                if bit_name in new_elements:
                    new_elements[bit_name].copy_state_from(old_elem)
            dev.elements = new_elements

            dev._cache.clear()
            # Log the change as a sim event so the log panel shows it
            self._frame_events.append({
                "type": "SETTINGS_CHANGE",
                "sim_time": self.sim_time_ms,
                "device_id": device_id,
            })
            return True

    def _cache_clear_all(self):
        for dev in self.devices.values():
            if hasattr(dev, "_cache"):
                dev._cache.clear()

sim_engine = SimEngine()
