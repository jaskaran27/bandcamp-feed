(function() {
    const player       = document.getElementById('audio-player');
    const audio        = document.getElementById('player-audio');
    const artEl        = document.getElementById('player-art');
    const titleEl      = document.getElementById('player-title');
    const artistEl     = document.getElementById('player-artist');
    const playPauseBtn = document.getElementById('player-playpause');
    const iconPlay     = document.getElementById('player-icon-play');
    const iconPause    = document.getElementById('player-icon-pause');
    const iconLoading  = document.getElementById('player-icon-loading');
    const progress     = document.getElementById('player-progress');
    const timeCur      = document.getElementById('player-time-current');
    const timeTotal    = document.getElementById('player-time-total');
    const trackCounter = document.getElementById('player-track-counter');
    const prevBtn      = document.getElementById('player-prev');
    const nextBtn      = document.getElementById('player-next');
    const closeBtn     = document.getElementById('player-close');

    let currentReleaseId = null;
    let releaseName = '';
    let tracks = [];
    let currentTrackIndex = 0;
    let refreshAttempted = false;
    let isSeeking = false;

    function fmt(seconds) {
        if (!seconds || !isFinite(seconds)) return '0:00';
        var m = Math.floor(seconds / 60);
        var s = Math.floor(seconds % 60);
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function showIcon(which) {
        iconPlay.classList.add('hidden');
        iconPause.classList.add('hidden');
        iconLoading.classList.add('hidden');
        which.classList.remove('hidden');
    }

    function showPlayer() {
        player.classList.remove('hidden');
        document.body.style.paddingBottom = player.offsetHeight + 'px';
    }

    function hidePlayer() {
        audio.pause();
        audio.removeAttribute('src');
        player.classList.add('hidden');
        document.body.style.paddingBottom = '';
        currentReleaseId = null;
        tracks = [];
        syncCardButtons();
    }

    function getPlaylist() {
        var items = [];
        document.querySelectorAll('[data-release-id]').forEach(function(btn) {
            items.push({
                id: parseInt(btn.getAttribute('data-release-id'), 10),
                title: btn.getAttribute('data-title') || '',
                artist: btn.getAttribute('data-artist') || '',
                artUrl: btn.getAttribute('data-art') || ''
            });
        });
        return items;
    }

    function getAdjacentRelease(direction) {
        var playlist = getPlaylist();
        for (var i = 0; i < playlist.length; i++) {
            if (playlist[i].id === currentReleaseId) {
                var target = i + direction;
                if (target >= 0 && target < playlist.length) return playlist[target];
                return null;
            }
        }
        return null;
    }

    function loadAndPlayRelease(entry) {
        refreshAttempted = false;
        currentReleaseId = entry.id;
        releaseName = entry.title;
        tracks = [];
        currentTrackIndex = 0;
        artistEl.textContent = entry.artist;
        artEl.src = entry.artUrl || '';
        titleEl.textContent = entry.title;
        trackCounter.classList.add('hidden');
        progress.value = 0;
        timeCur.textContent = '0:00';
        timeTotal.textContent = '0:00';
        showIcon(iconLoading);
        showPlayer();
        syncCardButtons();

        fetch('/stream/' + entry.id + '/')
            .then(function(r) {
                if (!r.ok) throw new Error('Stream not available');
                return r.json();
            })
            .then(function(data) {
                tracks = data.tracks || [];
                if (!tracks.length) throw new Error('No tracks');
                currentTrackIndex = 0;
                updateTrackDisplay();
                audio.src = tracks[0].stream_url;
                audio.play();
            })
            .catch(function() {
                showToast('Could not load stream for this release.', true);
                showIcon(iconPlay);
                syncCardButtons();
            });
    }

    function updateTrackDisplay() {
        if (tracks.length <= 1) {
            trackCounter.classList.add('hidden');
            titleEl.textContent = releaseName;
        } else {
            trackCounter.classList.remove('hidden');
            trackCounter.textContent = (currentTrackIndex + 1) + '/' + tracks.length;
            titleEl.textContent = tracks[currentTrackIndex].title;
        }
    }

    function playTrack(index) {
        if (index < 0 || index >= tracks.length) return;
        currentTrackIndex = index;
        refreshAttempted = false;
        updateTrackDisplay();
        progress.value = 0;
        timeCur.textContent = '0:00';
        timeTotal.textContent = '0:00';
        audio.src = tracks[index].stream_url;
        audio.play();
    }

    function syncCardButtons() {
        document.querySelectorAll('[data-release-id]').forEach(function(btn) {
            var id = parseInt(btn.getAttribute('data-release-id'), 10);
            var playIcon = btn.querySelector('.card-icon-play');
            var pauseIcon = btn.querySelector('.card-icon-pause');
            if (!playIcon || !pauseIcon) return;
            if (id === currentReleaseId && !audio.paused) {
                playIcon.classList.add('hidden');
                pauseIcon.classList.remove('hidden');
            } else {
                playIcon.classList.remove('hidden');
                pauseIcon.classList.add('hidden');
            }
        });
    }

    window.playRelease = function(id, title, artist, artUrl) {
        if (currentReleaseId === id && !audio.paused) {
            audio.pause();
            return;
        }
        if (currentReleaseId === id && audio.paused && audio.src) {
            audio.play();
            return;
        }
        loadAndPlayRelease({id: id, title: title, artist: artist, artUrl: artUrl});
    };

    playPauseBtn.addEventListener('click', function() {
        if (!audio.src) return;
        if (audio.paused) audio.play();
        else audio.pause();
    });

    prevBtn.addEventListener('click', function() {
        if (audio.currentTime > 3) {
            audio.currentTime = 0;
            return;
        }
        if (currentTrackIndex > 0) {
            playTrack(currentTrackIndex - 1);
        } else {
            var prev = getAdjacentRelease(-1);
            if (prev) loadAndPlayRelease(prev);
            else audio.currentTime = 0;
        }
    });

    nextBtn.addEventListener('click', function() {
        if (currentTrackIndex < tracks.length - 1) {
            playTrack(currentTrackIndex + 1);
        } else {
            var next = getAdjacentRelease(1);
            if (next) loadAndPlayRelease(next);
        }
    });

    audio.addEventListener('play', function() { showIcon(iconPause); syncCardButtons(); });
    audio.addEventListener('pause', function() { showIcon(iconPlay); syncCardButtons(); });

    audio.addEventListener('timeupdate', function() {
        if (isSeeking || !audio.duration) return;
        progress.value = (audio.currentTime / audio.duration) * 100;
        timeCur.textContent = fmt(audio.currentTime);
        timeTotal.textContent = fmt(audio.duration);
    });

    audio.addEventListener('loadedmetadata', function() {
        timeTotal.textContent = fmt(audio.duration);
    });

    audio.addEventListener('ended', function() {
        if (currentTrackIndex < tracks.length - 1) {
            playTrack(currentTrackIndex + 1);
        } else {
            var next = getAdjacentRelease(1);
            if (next) {
                loadAndPlayRelease(next);
            } else {
                showIcon(iconPlay);
                progress.value = 0;
                timeCur.textContent = '0:00';
                syncCardButtons();
            }
        }
    });

    progress.addEventListener('mousedown', function() { isSeeking = true; });
    progress.addEventListener('touchstart', function() { isSeeking = true; }, {passive: true});
    progress.addEventListener('input', function() {
        if (audio.duration) timeCur.textContent = fmt((progress.value / 100) * audio.duration);
    });
    progress.addEventListener('change', function() {
        if (audio.duration) audio.currentTime = (progress.value / 100) * audio.duration;
        isSeeking = false;
    });

    audio.addEventListener('error', function() {
        if (!currentReleaseId) return;
        if (refreshAttempted) {
            showToast('Could not play this track.', true);
            showIcon(iconPlay);
            syncCardButtons();
            return;
        }
        refreshAttempted = true;
        showIcon(iconLoading);

        fetch('/stream/' + currentReleaseId + '/?refresh=1')
            .then(function(r) {
                if (!r.ok) throw new Error('refresh failed');
                return r.json();
            })
            .then(function(data) {
                tracks = data.tracks || [];
                if (!tracks.length) throw new Error('No tracks');
                if (currentTrackIndex >= tracks.length) currentTrackIndex = 0;
                updateTrackDisplay();
                audio.src = tracks[currentTrackIndex].stream_url;
                audio.play();
            })
            .catch(function() {
                showToast('Could not play this track.', true);
                showIcon(iconPlay);
                syncCardButtons();
            });
    });

    closeBtn.addEventListener('click', hidePlayer);

    document.body.addEventListener('htmx:afterSwap', syncCardButtons);
})();
