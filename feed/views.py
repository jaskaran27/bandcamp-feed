import json
import logging

from django.shortcuts import render, get_object_or_404
from django.http import StreamingHttpResponse, JsonResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Release, FavouriteUploader
from .services import (
    fetch_new_releases, fetch_new_releases_streaming,
    get_cached_releases, get_feed_stats,
    scrape_stream_tracks, STREAM_URL_MAX_AGE_SECONDS,
)

logger = logging.getLogger(__name__)

RELEASES_PER_PAGE = 25


def get_filter_params(request):
    """Extract filter parameters from request."""
    return {
        'search': request.GET.get('search', '').strip(),
        'date_filter': request.GET.get('date', 'all'),
        'sort': request.GET.get('sort', 'newest'),
        'release_type': request.GET.get('type', 'all'),
        'favourites': request.GET.get('favourites', 'no'),
        'page': int(request.GET.get('page', 1)),
    }


def build_query_string(params, exclude=None):
    """Build query string from params, optionally excluding some keys."""
    exclude = exclude or []
    # Map internal param names to URL param names
    param_name_map = {'release_type': 'type', 'date_filter': 'date'}
    parts = []
    for key, value in params.items():
        if key not in exclude and value and value not in ('all', 'newest', 'no'):
            if key == 'page' and value == 1:
                continue
            url_key = param_name_map.get(key, key)
            parts.append(f"{url_key}={value}")
    return '&'.join(parts)


def index(request):
    """
    Main feed page with sync button and releases grid.
    """
    params = get_filter_params(request)
    
    releases, total_count, total_pages = get_cached_releases(
        page=params['page'],
        per_page=RELEASES_PER_PAGE,
        search=params['search'],
        date_filter=params['date_filter'],
        sort=params['sort'],
        release_type=params['release_type'],
        favourites=params['favourites'],
    )
    
    stats = get_feed_stats()
    
    # Build base query string for pagination links
    base_query = build_query_string(params, exclude=['page'])
    
    return render(request, 'feed/index.html', {
        'releases': releases,
        'release_count': total_count,
        'total_in_db': stats['total'],
        'current_page': params['page'],
        'total_pages': total_pages,
        'has_prev': params['page'] > 1,
        'has_next': params['page'] < total_pages,
        'prev_page': params['page'] - 1,
        'next_page': params['page'] + 1,
        'search': params['search'],
        'date_filter': params['date_filter'],
        'sort': params['sort'],
        'release_type': params['release_type'],
        'favourites': params['favourites'],
        'base_query': base_query,
        'stats': stats,
    })


def releases_partial(request):
    """
    HTMX partial endpoint returning just the releases grid HTML.
    """
    params = get_filter_params(request)
    
    releases, total_count, total_pages = get_cached_releases(
        page=params['page'],
        per_page=RELEASES_PER_PAGE,
        search=params['search'],
        date_filter=params['date_filter'],
        sort=params['sort'],
        release_type=params['release_type'],
        favourites=params['favourites'],
    )
    
    base_query = build_query_string(params, exclude=['page'])
    
    return render(request, 'feed/partials/releases.html', {
        'releases': releases,
        'release_count': total_count,
        'current_page': params['page'],
        'total_pages': total_pages,
        'has_prev': params['page'] > 1,
        'has_next': params['page'] < total_pages,
        'prev_page': params['page'] - 1,
        'next_page': params['page'] + 1,
        'search': params['search'],
        'date_filter': params['date_filter'],
        'sort': params['sort'],
        'release_type': params['release_type'],
        'favourites': params['favourites'],
        'base_query': base_query,
    })


@require_http_methods(["POST"])
def sync_releases(request):
    """
    HTMX endpoint to trigger IMAP fetch and return updated grid.
    """
    try:
        new_count = fetch_new_releases(
            email_user=settings.EMAIL_USER,
            email_password=settings.EMAIL_PASSWORD,
            email_host=settings.EMAIL_HOST,
            limit=getattr(settings, 'EMAIL_SYNC_LIMIT', 500),
        )
        
        releases, total_count, total_pages = get_cached_releases(page=1, per_page=RELEASES_PER_PAGE)
        
        response = render(request, 'feed/partials/releases.html', {
            'releases': releases,
            'sync_message': f"Synced! Found {new_count} new release{'s' if new_count != 1 else ''}.",
            'current_page': 1,
            'total_pages': total_pages,
            'has_prev': False,
            'has_next': total_pages > 1,
            'prev_page': 0,
            'next_page': 2,
            'search': '',
            'date_filter': 'all',
            'sort': 'newest',
            'release_type': 'all',
            'favourites': 'no',
            'base_query': '',
        })
        
        return response
        
    except ValueError as e:
        logger.error(f"Configuration error during sync: {e}")
        releases, total_count, total_pages = get_cached_releases(page=1, per_page=RELEASES_PER_PAGE)
        return render(request, 'feed/partials/releases.html', {
            'releases': releases,
            'error_message': str(e),
            'current_page': 1,
            'total_pages': total_pages,
            'has_prev': False,
            'has_next': total_pages > 1,
            'prev_page': 0,
            'next_page': 2,
            'search': '',
            'date_filter': 'all',
            'sort': 'newest',
            'release_type': 'all',
            'favourites': 'no',
            'base_query': '',
        })
        
    except Exception as e:
        logger.error(f"Error during sync: {e}")
        releases, total_count, total_pages = get_cached_releases(page=1, per_page=RELEASES_PER_PAGE)
        return render(request, 'feed/partials/releases.html', {
            'releases': releases,
            'error_message': f"Error connecting to email: {str(e)}",
            'current_page': 1,
            'total_pages': total_pages,
            'has_prev': False,
            'has_next': total_pages > 1,
            'prev_page': 0,
            'next_page': 2,
            'search': '',
            'date_filter': 'all',
            'sort': 'newest',
            'release_type': 'all',
            'favourites': 'no',
            'base_query': '',
        })


@require_http_methods(["GET"])
def sync_releases_stream(request):
    """
    Server-Sent Events endpoint for real-time sync progress.
    """
    def event_stream():
        try:
            for update in fetch_new_releases_streaming(
                email_user=settings.EMAIL_USER,
                email_password=settings.EMAIL_PASSWORD,
                email_host=settings.EMAIL_HOST,
                limit=getattr(settings, 'EMAIL_SYNC_LIMIT', 500),
            ):
                yield f"data: {json.dumps(update)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_http_methods(["POST"])
def toggle_favourite(request):
    """
    Toggle favourite status for an uploader.
    Returns the updated star button partial for HTMX swap.
    """
    uploader = request.POST.get('uploader', '').strip()
    artist = request.POST.get('artist', '').strip()
    if not uploader:
        return JsonResponse({'error': 'Missing uploader'}, status=400)
    
    fav, created = FavouriteUploader.objects.get_or_create(name=uploader)
    if not created:
        fav.delete()
        is_favourite = False
    else:
        is_favourite = True
    
    return render(request, 'feed/partials/favourite_btn.html', {
        'uploader': uploader,
        'artist': artist,
        'is_favourite': is_favourite,
    })


@require_http_methods(["GET"])
def get_stream_url(request, release_id):
    """
    Return the streaming tracklist for a release as JSON.

    Serves cached tracks when still fresh (< STREAM_URL_MAX_AGE_SECONDS).
    Accepts ``?refresh=1`` to force a re-scrape (used by the frontend after
    a playback error caused by an expired token).
    """
    release = get_object_or_404(Release, pk=release_id)
    force_refresh = request.GET.get('refresh') == '1'

    cache_is_fresh = (
        release.stream_tracks
        and release.stream_url_fetched_at
        and (timezone.now() - release.stream_url_fetched_at).total_seconds() < STREAM_URL_MAX_AGE_SECONDS
    )

    if not cache_is_fresh or force_refresh:
        tracks = scrape_stream_tracks(release.bandcamp_url)
        if tracks:
            release.stream_tracks = tracks
            release.stream_url_fetched_at = timezone.now()
            release.save(update_fields=['stream_tracks', 'stream_url_fetched_at'])
        else:
            return JsonResponse({'error': 'Could not extract stream tracks'}, status=404)

    return JsonResponse({
        'tracks': release.stream_tracks,
        'title': release.release_name,
        'artist': release.artist,
        'art_url': release.album_art_url,
    })
