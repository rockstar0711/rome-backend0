from django.core.management.base import BaseCommand
from api.models import *
import logging

# Set up logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Syncs data from Zenus API to ROME database'

    def handle(self, *args, **kwargs):
        try:
            generate_demo_data_for_los_angeles_2024()
            self.stdout.write(self.style.SUCCESS('Successfully synced data for Los Angeles 2024'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {str(e)}"))
            logger.error(f"Error generating demo data for Los Angeles 2024: {str(e)}")
            raise

def generate_demo_data_for_los_angeles_2024():
    """Create demo data for Los Angeles 2024 by copying from previous projects."""
    try:
        demo_project_id = 132  # Los Angeles 2024
        reference_project_ids = [354, 114, 71]  # Source projects

        # Ensure Los Angeles 2024 project exists
        demo_project = ProjectModel.objects.filter(id=demo_project_id).first()
        if not demo_project:
            print("Los Angeles 2024 project not found! Skipping demo data generation.")
            return

        # Ensure it has the necessary project types
        required_types = ["obs", "imp", "qr"]
        if not all(t in demo_project.type for t in required_types):
            demo_project.type = required_types
            demo_project.save()

        print(f"Updating demo data for project {demo_project.name}...")

        # Create session mapping to store old session id -> new session id
        session_mapping = {}
        device_mapping = {}  # To store mappings from old device_id to new device_id
        booth_mapping = {}  # To store mappings from old booth_id to new booth_id

        for ref_project_id in reference_project_ids:
            # Get the reference project
            ref_project = ProjectModel.objects.filter(id=ref_project_id).first()
            if not ref_project:
                print(f"Reference project {ref_project_id} not found! Skipping.")
                continue

            unique_qr_codes_count = ref_project.unique_qr_codes
            if unique_qr_codes_count > 0:
                demo_project.unique_qr_codes = unique_qr_codes_count
                demo_project.save()
                print(f"Stored unique_qr_codes for project {demo_project.name} from reference project {ref_project.name}.")
            else:
                print(f"Skipping unique_qr_codes for project {ref_project.name} as the count is 0.")

            # Copy the stages for the reference project to the new project
            for stage in ref_project.stages.all():
                new_stage, created = ProjectStageModel.objects.update_or_create(
                    name=stage.name,
                    project=demo_project,
                    defaults={'type': stage.type}
                )
                print(f"{'Created' if created else 'Updated'} stage: {new_stage.name} for project {demo_project.name}")

                # Copy the sessions for the stage
                for session in stage.sessions.all():
                    new_session, created = SessionModel.objects.update_or_create(
                        name=session.name,
                        project=demo_project,
                        project_stage=new_stage,
                        defaults={
                            'start_datetime': session.start_datetime,
                            'end_datetime': session.end_datetime,
                        }
                    )
                    session_mapping[session.id] = new_session.id  # Store mapping from old session ID to new session ID
                    print(f"{'Created' if created else 'Updated'} session: {new_session.name} for stage {new_stage.name}")

            # Copy the booths for the reference project
            ref_project_booths = ProjectBoothModel.objects.filter(project=ref_project)
            print(ref_project_booths)
            for booth in ref_project_booths:
                new_booth, created = ProjectBoothModel.objects.update_or_create(
                    booth_id=booth.booth_id + "demo",
                    name=booth.name,
                    project=demo_project,
                    defaults={
                        'size': booth.size,
                        'operating_hours': booth.operating_hours
                    }
                )
                booth_mapping[booth.id] = new_booth.id
                print(f"{'Created' if created else 'Updated'} booth: {new_booth.name} for project {demo_project.name}")

            # Copy the devices for the reference project
            for device in ref_project.devices.all():
                new_device_id = device.device_id + "_demo"  # Adding "demo" to device_id
                new_device, created = ProjectDeviceModel.objects.update_or_create(
                    device_id=new_device_id,
                    project=demo_project,
                    defaults={'name': device.name, 'service': device.service}
                )
                device_mapping[device.device_id] = new_device_id  # Save the mapping
                print(f"{'Created' if created else 'Updated'} device: {new_device.name} for project {demo_project.name}")

                # Update assignments: Convert old stage_id and booth_id to new ones
                new_assignments = []
                for assignment in device.assignments:
                    new_assignment = assignment.copy()  # Create a copy of the assignment dict

                    # Update stage_id if the assignment is related to a stage
                    if "stages" in new_assignment["areas"]:
                        old_stage_id = new_assignment["areas"][0]["id"]
                        new_stage = ProjectStageModel.objects.filter(project=demo_project, id=old_stage_id).first()
                        if new_stage:
                            new_assignment["areas"][0]["id"] = new_stage.id

                    # Update booth_id if the assignment is related to a booth
                    if "booths" in new_assignment["areas"]:
                        old_booth_id = new_assignment["areas"][0]["id"]
                        new_booth_id = booth_mapping.get(old_booth_id)
                        if new_booth_id:
                            new_assignment["areas"][0]["id"] = new_booth_id

                    new_assignments.append(new_assignment)

                new_device.assignments = new_assignments
                new_device.save()

            # Copy observations
            for observation in ref_project.observations.all():
                session = session_mapping.get(observation.session.id)  # Get new session ID
                new_device_id = device_mapping.get(observation.device_id)  # Get new device ID
                new_observation, created = ObservationModel.objects.update_or_create(
                    device_id=new_device_id,  # Store new device ID
                    session_id=session,  # Store the new session ID
                    datetime=observation.datetime,
                    project=demo_project,
                    defaults={
                        'device_name': observation.device_name,
                        'count_total': observation.count_total,
                        'count_male': observation.count_male,
                        'count_female': observation.count_female,
                        'count_under_40': observation.count_under_40,
                        'count_over_40': observation.count_over_40,
                        'energy': observation.energy,
                        'energy_male': observation.energy_male,
                        'energy_female': observation.energy_female,
                        'energy_under_40': observation.energy_under_40,
                        'energy_over_40': observation.energy_over_40
                    }
                )
                print(f"{'Created' if created else 'Updated'} observation for project {demo_project.name}")

            # Copy impressions
            ref_project_impressions = ImpressionModel.objects.filter(project=ref_project)
            for impression in ref_project_impressions:
                new_booth = booth_mapping.get(impression.booth.id)  # Get new booth ID
                new_device_id = device_mapping.get(impression.device_id)  # Get new device ID
                new_impression, created = ImpressionModel.objects.update_or_create(
                    device_id=new_device_id,  # Store new device ID
                    booth_id=new_booth,  # Store new booth ID
                    latest_datetime=impression.latest_datetime,
                    project=demo_project,
                    device_name=impression.device_name,
                    zone=impression.zone,
                    dwell_time=impression.dwell_time,
                    energy_median=impression.energy_median,
                    face_height_median=impression.face_height_median,
                    biological_sex=impression.biological_sex,
                    biological_age=impression.biological_age,
                )
                print(f"{'Created' if created else 'Updated'} impression for project {demo_project.name}")

            # Copy unique impressions
            ref_project_unique_impressions = UniqueImpressionModel.objects.filter(project=ref_project)
            for unique_impression in ref_project_unique_impressions:
                new_booth = booth_mapping.get(unique_impression.booth.id)  # Get new booth ID
                new_device_id = device_mapping.get(unique_impression.device_id)  # Get new device ID
                new_unique_impression, created = UniqueImpressionModel.objects.update_or_create(
                    device_id=new_device_id,  # Store new device ID
                    booth_id=new_booth,  # Store new booth ID
                    project=demo_project,
                    date=unique_impression.date,
                    zone=unique_impression.zone,
                    is_staff=unique_impression.is_staff,
                    impressions_total=unique_impression.impressions_total,
                    visit_duration=unique_impression.visit_duration,
                    dwell_time=unique_impression.dwell_time,
                    energy_median=unique_impression.energy_median,
                    face_height_median=unique_impression.face_height_median,
                    biological_sex=unique_impression.biological_sex,
                    biological_age=unique_impression.biological_age,
                )
                print(f"{'Created' if created else 'Updated'} unique impression for project {demo_project.name}")

            # Copy QrCode data
            ref_project_qr_codes = QrCodeModel.objects.filter(project=ref_project)
            for qr_code in ref_project_qr_codes:
                # Check if session exists
                if qr_code.session:
                    session = session_mapping.get(qr_code.session.id)  # Get new session ID
                else:
                    session = None  # If session is None, set it to None
                new_device_id = device_mapping.get(qr_code.device_id)  # Get new device ID
                new_qr_code, created = QrCodeModel.objects.update_or_create(
                    device_id=new_device_id,  # Store new device ID
                    session_id=session,  # Store new session ID
                    project=demo_project,
                    datetime=qr_code.datetime,
                    qr_code=qr_code.qr_code,
                    defaults={
                        'device_name': qr_code.device_name,
                        'dwell_time': qr_code.dwell_time
                    }
                )
                print(f"{'Created' if created else 'Updated'} QR code for project {demo_project.name}")

            # Copy ImpressionAnalyticsModel
            ref_project_impression_analytics = ImpressionAnalyticsModel.objects.filter(project=ref_project)
            for impression_analytics in ref_project_impression_analytics:
                new_impression_analytics, created = ImpressionAnalyticsModel.objects.update_or_create(
                    project=demo_project,
                    zone=impression_analytics.zone,
                    date=impression_analytics.date,
                    defaults={
                        'impression_count': impression_analytics.impression_count,
                        'total_impressions': impression_analytics.total_impressions
                    }
                )
                print(f"{'Created' if created else 'Updated'} ImpressionAnalyticsModel for project {demo_project.name}")

            # Copy SessionAnalyticsModel
            ref_project_session_analytics = SessionAnalyticsModel.objects.filter(project=ref_project)
            for session_analytics in ref_project_session_analytics:
                session = session_mapping.get(session_analytics.session.id)  # Get new session ID
                new_session_analytics, created = SessionAnalyticsModel.objects.update_or_create(
                    project=demo_project,
                    session_id=session,  # Store new session ID
                    defaults={
                        'male_ratio': session_analytics.male_ratio,
                        'female_ratio': session_analytics.female_ratio,
                        'under_40_ratio': session_analytics.under_40_ratio,
                        'over_40_ratio': session_analytics.over_40_ratio,
                        'energy_avg': session_analytics.energy_avg,
                        'male_energy_avg': session_analytics.male_energy_avg,
                        'female_energy_avg': session_analytics.female_energy_avg,
                        'under_40_energy_avg': session_analytics.under_40_energy_avg,
                        'over_40_energy_avg': session_analytics.over_40_energy_avg
                    }
                )
                print(f"{'Created' if created else 'Updated'} SessionAnalyticsModel for project {demo_project.name}")

        print(f"Demo data generation for Los Angeles 2024 completed successfully!")

    except Exception as e:
        print(f"Error generating demo data for Los Angeles 2024: {str(e)}")