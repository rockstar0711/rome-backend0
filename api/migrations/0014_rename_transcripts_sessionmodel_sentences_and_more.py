# Generated by Django 5.1.4 on 2025-06-03 19:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0013_remove_sessionmodel_transcript_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='sessionmodel',
            old_name='transcripts',
            new_name='sentences',
        ),
        migrations.AddField(
            model_name='sessionmodel',
            name='transcript',
            field=models.TextField(blank=True, null=True),
        ),
    ]
