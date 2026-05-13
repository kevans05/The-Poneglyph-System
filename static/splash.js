"use strict";

window.addEventListener('load', () => {
    setTimeout(() => {
        const splash = document.getElementById('splash-screen');
        if (splash) {
            splash.style.opacity = '0';
            setTimeout(() => {
                splash.style.visibility = 'hidden';

                // Check whether a site is already active (server remembers within session).
                // If not, show the site selector before loading topology.
                fetchActiveSite().then(resp => {
                    if (resp.active && resp.info) {
                        _activeSiteInfo = resp.info;
                        _updateSiteIndicator(resp.info.station);
                        refreshData();
                    } else {
                        showSiteSelector({ onLoaded: () => {} });
                    }
                }).catch(() => {
                    // Server unreachable or no sites exist yet — show selector anyway
                    showSiteSelector({ onLoaded: () => {} });
                });

            }, 800);
        }
    }, 3000);
});
