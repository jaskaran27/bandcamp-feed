"""
Service module for IMAP email fetching and parsing Bandcamp new release notifications.
"""

from django.db.models import Q
from django.db.models import Count

import re
import logging
from urllib.parse import urlparse, urlunparse
from datetime import timedelta
from django.utils import timezone
from typing import Generator
from bs4 import BeautifulSoup
from imap_tools import MailBox, AND


from .models import Release

logger = logging.getLogger(__name__)

# Default limit for emails to process per sync (to handle large backlogs)
DEFAULT_EMAIL_LIMIT = 500


def clean_url(url: str) -> str:
    """Remove query parameters from a URL."""
    if not url:
        return url
    parsed = urlparse(url)
    # Rebuild URL without query params and fragment
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))


def is_bandcamp_release_url(url: str) -> bool:
    """
    Check if a URL is a valid Bandcamp release URL.
    This includes both .bandcamp.com subdomains AND custom domains.
    
    Valid patterns:
    - https://artist.bandcamp.com/album/name
    - https://artist.bandcamp.com/track/name
    - https://customdomain.com/album/name (custom domain)
    - https://customdomain.com/track/name (custom domain)
    """
    if not url:
        return False
    
    # Must have /album/ or /track/ in the path
    if '/album/' not in url and '/track/' not in url:
        return False
    
    return True


def is_bandcamp_unsubscribe_url(url: str) -> bool:
    """Check if URL is a Bandcamp unsubscribe/unfollow link."""
    return 'unsubscribe' in url.lower() or 'unfollow' in url.lower()


def clean_uploader_name(name: str) -> str:
    """
    Clean the uploader name by removing ", who brought you..." suffix.
    """
    if not name:
        return name
    # Remove ", who brought you..." and everything after
    match = re.match(r'^(.+?),?\s*who brought you', name, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return name.strip()


def parse_bandcamp_email(html_content: str, subject: str) -> dict:
    """
    Parse a Bandcamp new release notification email for metadata.
    
    Args:
        html_content: The HTML body of the email
        subject: The email subject line
        
    Returns:
        Dictionary with uploader, release_name, album_art_url, and bandcamp_url
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract uploader from subject line: "New release from [Uploader Name]"
    uploader = ""
    subject_match = re.search(r'New release from (.+)', subject, re.IGNORECASE)
    if subject_match:
        uploader = clean_uploader_name(subject_match.group(1))
    
    # Get the text content of the email
    text_content = soup.get_text(separator=' ', strip=True)
    
    # Extract release name from email body
    release_name = ""
    release_patterns = [
        r'just released\s+(.+?)(?:,\s*check it out|\.|\s*$)',
        r'just announced\s+(.+?)(?:,\s*check it out|\.|\s*$)',
    ]
    
    for pattern in release_patterns:
        match = re.search(pattern, text_content, re.IGNORECASE)
        if match:
            release_name = match.group(1).strip()
            break
    
    # Extract album art URL - look for the main album image
    album_art_url = ""
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if 'bcbits.com' in src:
            album_art_url = src
            break
    
    # Extract Bandcamp URL - multiple strategies
    bandcamp_url = ""
    
    # Strategy 1: Look for "check it out" link (most reliable)
    for link in soup.find_all('a', href=True):
        link_text = link.get_text(strip=True).lower()
        if 'check it out' in link_text:
            href = link.get('href', '')
            cleaned = clean_url(href)
            if is_bandcamp_release_url(cleaned) and not is_bandcamp_unsubscribe_url(cleaned):
                bandcamp_url = cleaned
                break
    
    # Strategy 2: Look for any album/track link
    if not bandcamp_url:
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            cleaned = clean_url(href)
            if is_bandcamp_release_url(cleaned) and not is_bandcamp_unsubscribe_url(cleaned):
                bandcamp_url = cleaned
                break
    
    return {
        'uploader': uploader,
        'release_name': release_name,
        'album_art_url': album_art_url,
        'bandcamp_url': bandcamp_url,
    }


def get_sync_cutoff_date():
    """
    Get the date to use as a cutoff for syncing.
    
    Strategy:
    - If we have releases, start from the OLDEST one we have (to continue backwards)
    - If no releases yet, return None (scan from newest)
    
    This ensures we gradually process all historical emails over multiple syncs.
    """
    oldest_release = Release.objects.order_by('received_at').first()
    if oldest_release:
        # Add a small buffer to avoid edge cases
        return oldest_release.received_at - timedelta(days=1)
    return None


def fetch_new_releases_streaming(
    email_user: str,
    email_password: str,
    email_host: str = 'imap.gmail.com',
    limit: int = DEFAULT_EMAIL_LIMIT
) -> Generator[dict, None, None]:
    """
    Generator that yields sync progress updates for real-time UI feedback.
    
    Sync strategy:
    1. First, scan recent emails (newest first) to catch any new releases
    2. Then, continue from where we left off (oldest synced release) going backwards
    
    This ensures:
    - New releases are always caught quickly
    - Historical emails are gradually processed over multiple syncs
    
    Yields dicts with keys:
    - type: 'progress' | 'added' | 'complete' | 'error'
    - For 'progress': processed, total_found, skipped, message
    - For 'added': uploader, release_name
    - For 'complete': new_count, total_processed
    - For 'error': message
    """
    if not email_user or not email_password:
        yield {'type': 'error', 'message': 'Email credentials not configured'}
        return
    
    existing_ids = set(Release.objects.values_list('email_id', flat=True))
    existing_urls = set(Release.objects.values_list('bandcamp_url', flat=True))
    
    # Get the cutoff date for historical scanning
    cutoff_date = get_sync_cutoff_date()
    
    new_count = 0
    processed_count = 0
    skipped_count = 0
    new_found_in_recent = 0
    reached_limit = False
    
    try:
        yield {'type': 'progress', 'message': 'Connecting to email server...', 'processed': 0, 'new_count': 0}
        
        with MailBox(email_host).login(email_user, email_password) as mailbox:
            folders = list(mailbox.folder.list())
            
            # Phase 1: Scan recent emails first (to catch new releases)
            yield {'type': 'progress', 'message': 'Checking for new releases...', 'processed': 0, 'new_count': 0}
            
            # Limit for phase 1 - just check recent emails quickly
            recent_limit = min(100, limit // 2) if limit > 0 else 100
            recent_processed = 0
            
            for folder_info in folders:
                if recent_processed >= recent_limit:
                    break
                    
                folder_name = folder_info.name
                
                if folder_info.flags and '\\Noselect' in folder_info.flags:
                    continue
                
                try:
                    mailbox.folder.set(folder_name)
                except Exception:
                    continue
                
                # Fetch newest emails first
                messages = mailbox.fetch(
                    AND(from_='noreply@bandcamp.com'),
                    reverse=True,  # Newest first
                    mark_seen=False
                )
                
                for msg in messages:
                    if recent_processed >= recent_limit:
                        break
                    
                    subject = msg.subject or ""
                    if 'new release from' not in subject.lower():
                        continue
                    
                    recent_processed += 1
                    processed_count += 1
                    email_id = f"{folder_name}:{msg.uid}"
                    
                    # If we hit an email we already have, we've caught up on recent
                    if email_id in existing_ids:
                        skipped_count += 1
                        # After hitting 10 existing in a row in recent scan, move to historical
                        continue
                    
                    html_content = msg.html or msg.text or ""
                    if not html_content:
                        skipped_count += 1
                        continue
                    
                    parsed = parse_bandcamp_email(html_content, subject)
                    
                    if not parsed['uploader'] or not parsed['bandcamp_url'] or not parsed['release_name']:
                        skipped_count += 1
                        continue
                    
                    if parsed['bandcamp_url'] in existing_urls:
                        skipped_count += 1
                        continue
                    
                    # Determine release type from URL
                    release_type = Release.RELEASE_TYPE_TRACK if '/track/' in parsed['bandcamp_url'] else Release.RELEASE_TYPE_ALBUM
                    
                    Release.objects.create(
                        email_id=email_id,
                        uploader=parsed['uploader'],
                        release_name=parsed['release_name'],
                        album_art_url=parsed['album_art_url'],
                        bandcamp_url=parsed['bandcamp_url'],
                        release_type=release_type,
                        received_at=msg.date or timezone.now(),
                    )
                    
                    existing_urls.add(parsed['bandcamp_url'])
                    existing_ids.add(email_id)
                    new_count += 1
                    new_found_in_recent += 1
                    
                    yield {
                        'type': 'added',
                        'uploader': parsed['uploader'],
                        'release_name': parsed['release_name'],
                        'processed': processed_count,
                        'new_count': new_count,
                    }
            
            # Phase 2: Continue with historical emails (older than our oldest release)
            if cutoff_date and (limit == 0 or processed_count < limit):
                yield {
                    'type': 'progress',
                    'message': f'Scanning historical emails (before {cutoff_date.strftime("%b %d, %Y")})...',
                    'processed': processed_count,
                    'new_count': new_count,
                }
                
                for folder_info in folders:
                    if reached_limit:
                        break
                        
                    folder_name = folder_info.name
                    
                    if folder_info.flags and '\\Noselect' in folder_info.flags:
                        continue
                    
                    try:
                        mailbox.folder.set(folder_name)
                    except Exception:
                        continue
                    
                    # Fetch emails BEFORE the cutoff date (oldest first to work backwards)
                    messages = mailbox.fetch(
                        AND(
                            from_='noreply@bandcamp.com',
                            date_lt=cutoff_date.date()
                        ),
                        reverse=True,  # Start from most recent of the old ones
                        mark_seen=False
                    )
                    
                    for msg in messages:
                        subject = msg.subject or ""
                        if 'new release from' not in subject.lower():
                            continue
                        
                        if limit > 0 and processed_count >= limit:
                            reached_limit = True
                            break
                        
                        processed_count += 1
                        email_id = f"{folder_name}:{msg.uid}"
                        
                        if email_id in existing_ids:
                            skipped_count += 1
                            continue
                        
                        html_content = msg.html or msg.text or ""
                        if not html_content:
                            skipped_count += 1
                            continue
                        
                        parsed = parse_bandcamp_email(html_content, subject)
                        
                        if not parsed['uploader'] or not parsed['bandcamp_url'] or not parsed['release_name']:
                            skipped_count += 1
                            continue
                        
                        if parsed['bandcamp_url'] in existing_urls:
                            skipped_count += 1
                            continue
                        
                        # Determine release type from URL
                        release_type = Release.RELEASE_TYPE_TRACK if '/track/' in parsed['bandcamp_url'] else Release.RELEASE_TYPE_ALBUM
                        
                        Release.objects.create(
                            email_id=email_id,
                            uploader=parsed['uploader'],
                            release_name=parsed['release_name'],
                            album_art_url=parsed['album_art_url'],
                            bandcamp_url=parsed['bandcamp_url'],
                            release_type=release_type,
                            received_at=msg.date or timezone.now(),
                        )
                        
                        existing_urls.add(parsed['bandcamp_url'])
                        existing_ids.add(email_id)
                        new_count += 1
                        
                        yield {
                            'type': 'added',
                            'uploader': parsed['uploader'],
                            'release_name': parsed['release_name'],
                            'processed': processed_count,
                            'new_count': new_count,
                        }
                        
                        # Yield progress every 10 emails
                        if processed_count % 10 == 0:
                            yield {
                                'type': 'progress',
                                'message': 'Processing historical emails...',
                                'processed': processed_count,
                                'new_count': new_count,
                            }
            
            elif not cutoff_date:
                # No existing releases - this is first sync, continue scanning all
                yield {
                    'type': 'progress',
                    'message': 'First sync - processing all emails...',
                    'processed': processed_count,
                    'new_count': new_count,
                }
                
                # Continue where phase 1 left off
                for folder_info in folders:
                    if reached_limit:
                        break
                        
                    folder_name = folder_info.name
                    
                    if folder_info.flags and '\\Noselect' in folder_info.flags:
                        continue
                    
                    try:
                        mailbox.folder.set(folder_name)
                    except Exception:
                        continue
                    
                    messages = mailbox.fetch(
                        AND(from_='noreply@bandcamp.com'),
                        reverse=True,
                        mark_seen=False
                    )
                    
                    for msg in messages:
                        subject = msg.subject or ""
                        if 'new release from' not in subject.lower():
                            continue
                        
                        if limit > 0 and processed_count >= limit:
                            reached_limit = True
                            break
                        
                        processed_count += 1
                        email_id = f"{folder_name}:{msg.uid}"
                        
                        if email_id in existing_ids:
                            skipped_count += 1
                            continue
                        
                        html_content = msg.html or msg.text or ""
                        if not html_content:
                            skipped_count += 1
                            continue
                        
                        parsed = parse_bandcamp_email(html_content, subject)
                        
                        if not parsed['uploader'] or not parsed['bandcamp_url'] or not parsed['release_name']:
                            skipped_count += 1
                            continue
                        
                        if parsed['bandcamp_url'] in existing_urls:
                            skipped_count += 1
                            continue
                        
                        # Determine release type from URL
                        release_type = Release.RELEASE_TYPE_TRACK if '/track/' in parsed['bandcamp_url'] else Release.RELEASE_TYPE_ALBUM
                        
                        Release.objects.create(
                            email_id=email_id,
                            uploader=parsed['uploader'],
                            release_name=parsed['release_name'],
                            album_art_url=parsed['album_art_url'],
                            bandcamp_url=parsed['bandcamp_url'],
                            release_type=release_type,
                            received_at=msg.date or timezone.now(),
                        )
                        
                        existing_urls.add(parsed['bandcamp_url'])
                        existing_ids.add(email_id)
                        new_count += 1
                        
                        yield {
                            'type': 'added',
                            'uploader': parsed['uploader'],
                            'release_name': parsed['release_name'],
                            'processed': processed_count,
                            'new_count': new_count,
                        }
                        
                        if processed_count % 10 == 0:
                            yield {
                                'type': 'progress',
                                'message': 'Processing emails...',
                                'processed': processed_count,
                                'new_count': new_count,
                            }
        
        yield {
            'type': 'complete',
            'new_count': new_count,
            'processed': processed_count,
            'skipped': skipped_count,
            'reached_limit': reached_limit,
            'new_in_recent': new_found_in_recent,
        }
        
    except Exception as e:
        yield {'type': 'error', 'message': str(e)}


def fetch_new_releases(
    email_user: str,
    email_password: str,
    email_host: str = 'imap.gmail.com',
    limit: int = DEFAULT_EMAIL_LIMIT
) -> int:
    """
    Connect to Gmail via IMAP, fetch Bandcamp new release emails,
    parse them, and save to database.
    
    Returns:
        Number of new releases added
    """
    new_count = 0
    for update in fetch_new_releases_streaming(email_user, email_password, email_host, limit):
        if update['type'] == 'error':
            raise ValueError(update['message'])
        elif update['type'] == 'complete':
            new_count = update['new_count']
        elif update['type'] == 'added':
            print(f"[DEBUG] Added: {update['uploader']} - {update['release_name']}")
    
    return new_count


def get_cached_releases(
    page: int = 1,
    per_page: int = 25,
    search: str = '',
    date_filter: str = 'all',
    sort: str = 'newest',
    release_type: str = 'all'
):
    """
    Get paginated and filtered cached releases.
    
    Args:
        page: Page number (1-indexed)
        per_page: Number of releases per page
        search: Search query for uploader or release name
        date_filter: 'all', 'week', 'month', '3months', 'year'
        sort: 'newest', 'oldest', 'uploader_az', 'uploader_za'
        release_type: 'all', 'album', 'track'
    
    Returns:
        Tuple of (releases queryset, total_count, total_pages)
    """
    releases = Release.objects.all()
    
    # Apply search filter
    if search:
        releases = releases.filter(
            Q(uploader__icontains=search) | Q(release_name__icontains=search)
        )
    
    # Apply date filter
    if date_filter != 'all':
        now = timezone.now()
        if date_filter == 'week':
            cutoff = now - timedelta(days=7)
        elif date_filter == 'month':
            cutoff = now - timedelta(days=30)
        elif date_filter == '3months':
            cutoff = now - timedelta(days=90)
        elif date_filter == 'year':
            cutoff = now - timedelta(days=365)
        else:
            cutoff = None
        
        if cutoff:
            releases = releases.filter(received_at__gte=cutoff)
    
    # Apply release type filter
    if release_type in ('album', 'track'):
        releases = releases.filter(release_type=release_type.upper())
    
    # Apply sorting
    if sort == 'newest':
        releases = releases.order_by('-received_at')
    elif sort == 'oldest':
        releases = releases.order_by('received_at')
    elif sort == 'uploader_az':
        releases = releases.order_by('uploader', '-received_at')
    elif sort == 'uploader_za':
        releases = releases.order_by('-uploader', '-received_at')
    else:
        releases = releases.order_by('-received_at')
    
    total_count = releases.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    start = (page - 1) * per_page
    end = start + per_page
    
    return releases[start:end], total_count, total_pages


def get_feed_stats():
    """
    Get statistics about the feed for the dashboard.
    
    Returns:
        Dictionary with stats
    """
    
    total = Release.objects.count()
    
    now = timezone.now()
    this_week = Release.objects.filter(received_at__gte=now - timedelta(days=7)).count()
    this_month = Release.objects.filter(received_at__gte=now - timedelta(days=30)).count()
    
    # Top uploaders (top 10)
    top_uploaders = (
        Release.objects
        .values('uploader')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    
    # Date range
    oldest = Release.objects.order_by('received_at').first()
    newest = Release.objects.order_by('-received_at').first()
    
    return {
        'total': total,
        'this_week': this_week,
        'this_month': this_month,
        'top_uploaders': list(top_uploaders),
        'oldest_date': oldest.received_at if oldest else None,
        'newest_date': newest.received_at if newest else None,
    }
