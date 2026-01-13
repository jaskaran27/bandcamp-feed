from django.db import models


class Release(models.Model):
    """
    Cached Bandcamp release information parsed from notification emails.
    """
    RELEASE_TYPE_ALBUM = 'ALBUM'
    RELEASE_TYPE_TRACK = 'TRACK'
    RELEASE_TYPE_CHOICES = [
        (RELEASE_TYPE_ALBUM, 'Album'),
        (RELEASE_TYPE_TRACK, 'Track'),
    ]
    
    email_id = models.CharField(max_length=255, unique=True)  # IMAP UID for deduplication
    uploader = models.CharField(max_length=255)  # Artist or label name
    release_name = models.CharField(max_length=255)  # Album, EP, single, or track name
    album_art_url = models.URLField(max_length=500)
    bandcamp_url = models.URLField(max_length=500)
    release_type = models.CharField(max_length=10, choices=RELEASE_TYPE_CHOICES, default=RELEASE_TYPE_ALBUM)
    received_at = models.DateTimeField()  # Email received date for chronological ordering
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']
        verbose_name = 'Release'
        verbose_name_plural = 'Releases'

    def __str__(self):
        return f"{self.uploader} - {self.release_name}"