from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feed', '0004_release_artist'),
    ]

    operations = [
        migrations.AddField(
            model_name='release',
            name='stream_tracks',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='release',
            name='stream_url_fetched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
