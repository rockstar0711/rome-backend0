# Generated by Django 5.1.4 on 2025-03-07 08:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_qrcodedwelltimemodel'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectmodel',
            name='unique_qr_codes',
            field=models.IntegerField(default=0),
        ),
    ]
