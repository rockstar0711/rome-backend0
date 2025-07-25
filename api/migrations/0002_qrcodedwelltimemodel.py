# Generated by Django 5.1.4 on 2025-03-06 15:41

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='QrCodeDwellTimeModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('dwell_time', models.IntegerField(help_text='Time in minutes')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qr_code_dwell_times', to='api.projectmodel')),
                ('qr_code', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dwell_times', to='api.qrcodemodel')),
            ],
        ),
    ]
