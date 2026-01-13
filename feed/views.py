import json
import logging

from django.shortcuts import render
from django.http import StreamingHttpResponse
from django.conf import settings
from django.views.decorators.http import require_http_methods

from .services import fetch_new_releases, fetch_new_releases_streaming, get_cached_releases, get_feed_stats

logger = logging.getLogger(__name__)

RELEASES_PER_PAGE = 25


def get_filter_params(request):
    """Extract filter parameters from request."""
    return {
        'search': request.GET.get('search', '').strip(),
        'date_filter': request.GET.get('date', 'all'),
        'sort': request.GET.get('sort', 'newest'),
        'release_type': request.GET.get('type', 'all'),
        'page': int(request.GET.get('page', 1)),
    }


def build_query_string(params, exclude=None):
    """Build query string from params, optionally excluding some keys."""
    exclude = exclude or []
    # Map internal param names to URL param names
    param_name_map = {'release_type': 'type', 'date_filter': 'date'}
    parts = []
    for key, value in params.items():
        if key not in exclude and value and value != 'all' and value != 'newest':
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
