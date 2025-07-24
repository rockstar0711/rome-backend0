import os
import requests
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.db import IntegrityError, DatabaseError, transaction
from api.models import *
from collections import defaultdict
from django.db.models import Avg
from datetime import timedelta, datetime
from dateutil import parser

# Load Zenus API URL and API key from environment variables
ZENUS_API_URL = os.environ.get("ZENUS_API_URL")

def fetch_zenus_data(endpoint, params=None):
    """Helper function to handle API requests."""
    ZENUS_API_KEY = os.environ.get("ZENUS_API_KEY")  # Use current API key in the environment variable
    HEADERS = {
        "Authorization": f"Bearer {ZENUS_API_KEY}",
    }
    response = requests.get(f"{ZENUS_API_URL}/{endpoint}", headers=HEADERS, params=params)
    if response.status_code != 200:
        raise Exception(f"Error fetching data from Zenus: {response.text}")
    return response.json()

class Command(BaseCommand):
    help = 'Syncs data from Zenus API to ROME database'

    def handle(self, *args, **kwargs):
        try:
            # print(f"start with {489}.")
            # sync_single_project(489)
            projects = sync_project_list()
            if not projects:
                self.stdout.write("No projects found to sync.")
                return

            # Loop through each project and call sync_single_project for each one
            for project in projects:
                try:
                    # Sync each individual project
                    sync_single_project(project['id'])
                except Exception as e:
                    self.stderr.write(f"Error while processing project {project['id']}: {str(e)}")

        except Exception as e:
            # General error handling for fetching Zenus data or other unexpected errors
            self.stderr.write(f"An error occurred while syncing data: {str(e)}")

def sync_project_list():
    """Sync all projects."""
    try:
        # Fetch all projects from Zenus
        projects_data = fetch_zenus_data('projects')
        projects = projects_data.get('projects', [])

        if not projects:
            print("No projects found to sync.")
            return

        # Process each project
        for project_data in projects:
            try:
                project_data = fetch_zenus_data(f'projects/{project_data['id']}')
                if not project_data:
                    print(f"No data found for project {project_data['id']}.")
                    return None
                
                # Update or create the project
                project, created = ProjectModel.objects.update_or_create(
                    id=project_data['id'],
                    defaults={
                        'name': project_data['name'],
                        'start_datetime': timezone.make_aware(timezone.datetime.fromisoformat(project_data['start_datetime'])),
                        'end_datetime': timezone.make_aware(timezone.datetime.fromisoformat(project_data['end_datetime'])),
                        'deployment_timezone': project_data['deployment_timezone'],
                        'services': project_data['services'],
                        'country': project_data['country'],
                        'city': project_data['city'],
                    }
                )
               
                if created:
                    print(f"Project {project.name} created.")
                else:
                    print(f"Project {project.name} updated.")

            except IntegrityError as e:
                print(f"Integrity error while processing project {project_data['id']}: {str(e)}")
            except DatabaseError as e:
                print(f"Database error while processing project {project_data['id']}: {str(e)}")
            except Exception as e:
                print(f"Error while processing project {project_data['id']}: {str(e)}")
        
        return projects
    except Exception as e:
        print(f"Error syncing project list: {str(e)}")
        return []

def sync_single_project(project_id):
    """Sync a single project."""
    try:
        # Fetch project data
        project_data = fetch_zenus_data(f'projects/{project_id}')
        if not project_data:
            print(f"No data found for project {project_id}.")
            return None
        
        # Update or create the project
        project, created = ProjectModel.objects.update_or_create(
            id=project_data['id'],
            defaults={
                'name': project_data['name'],
                'start_datetime': timezone.make_aware(timezone.datetime.fromisoformat(project_data['start_datetime'])),
                'end_datetime': timezone.make_aware(timezone.datetime.fromisoformat(project_data['end_datetime'])),
                'deployment_timezone': project_data['deployment_timezone'],
                'services': project_data['services'],
                'country': project_data['country'],
                'city': project_data['city'],
            }
        )

        sync_project_stage(project)
        sync_project_booths(project)
        sync_project_devices(project)
        sync_project_observations(project)
        calculate_and_save_analytics(project)
        sync_project_impressions(project)
        sync_project_unique_impressions(project)
        calculate_impression_analytics(project, zone="internal")
        calculate_impression_analytics(project, zone="aisle")
        sync_project_qr_codes(project)
        calculate_qr_code_dwell_time(project)
        calculate_project_qr_codes(project)

        return project
    
    except IntegrityError as e:
        print(f"Integrity error while processing project {project_id}: {str(e)}")
    except DatabaseError as e:
        print(f"Database error while processing project {project_id}: {str(e)}")
    except Exception as e:
        print(f"Error while processing project {project_id}: {str(e)}")
    return None

def sync_project_stage(project):
    """Store or update a project stage."""
    try:
        # Fetch project stages data using the new API endpoint
        stages_data = fetch_zenus_data(f'projects/{project.id}/stages?include=sessions')

        if stages_data and 'stages' in stages_data:
            stages = stages_data['stages']
            for stage_data in stages:
                try:
                    # Create or update the stage, ensuring we store the id
                    stage, created = ProjectStageModel.objects.update_or_create(
                        id=stage_data['id'],  # Use the stage's id
                        project=project,
                        name=stage_data['name'],
                        defaults={'name': stage_data['name']}
                    )

                    if created:
                        print(f"Stage {stage.name} created for project {project.name}.")
                    else:
                        print(f"Stage {stage.name} updated for project {project.name}.")

                    # Sync sessions for this stage (you can create a separate function for sessions if needed)
                    sync_project_sessions(project, stage, stage_data.get("sessions", []))

                except Exception as e:
                    print(f"Error while processing stage {stage_data['name']} for project {project.name}: {str(e)}")
    except Exception as e:
        print(f"Error while syncing stages for project {project.name}: {str(e)}")

def sync_project_sessions(project, stage, sessions_data):
    """Sync sessions for each stage."""
    for session_data in sessions_data:
        try:
            # Update or create the session in the database
            session, created = SessionModel.objects.update_or_create(
                # Include fields that uniquely identify the session
                name=session_data['name'],
                project=project,
                start_datetime=timezone.make_aware(timezone.datetime.fromisoformat(session_data['start_datetime'])),
                end_datetime=timezone.make_aware(timezone.datetime.fromisoformat(session_data['end_datetime'])),
                project_stage=stage
                # defaults={
                #     'project_stage': stage
                # }
            )
            if created:
                print(f"Session {session.id} created for stage {stage.name}.")
            else:
                print(f"Session {session.id} updated for stage {stage.name}.")

        except Exception as e:
            print(f"Error while processing session {session_data['name']} for stage {stage.name}: {str(e)}")

def sync_project_booths(project):
    """Sync booths for a given project."""
    try:
        # Fetch booths data using the new API endpoint
        booths_data = fetch_zenus_data(f'projects/{project.id}/booths?include=operatingHours')

        if booths_data and 'booths' in booths_data:
            booths = booths_data['booths']
            for booth_data in booths:
                try:
                    # Create or update the booth
                    booth, created = ProjectBoothModel.objects.update_or_create(
                        booth_id=booth_data['id'],  # Use the booth ID as unique
                        project=project,
                        defaults={
                            'name': booth_data['name'],
                            'size': booth_data['size'],
                            'operating_hours': booth_data.get('operating_hours', []),  # Store operating hours directly
                        }
                    )

                    if created:
                        print(f"Booth {booth.name} created for project {project.name}.")
                    else:
                        print(f"Booth {booth.name} updated for project {project.name}.")

                except Exception as e:
                    print(f"Error while processing booth {booth_data['name']} for project {project.name}: {str(e)}")

    except Exception as e:
        print(f"Error while syncing booths for project {project.name}: {str(e)}")

def sync_project_devices(project):
    """Sync devices for a given project."""
    try:
        # Fetch devices data using the new API endpoint
        devices_data = fetch_zenus_data(f'projects/{project.id}/devices?include=assignments')

        if devices_data and 'devices' in devices_data:
            devices = devices_data['devices']
            for device_data in devices:
                try:
                    # Create or update the device
                    device, created = ProjectDeviceModel.objects.update_or_create(
                        device_id=device_data['id'],
                        project=project,
                        defaults={
                            'name': device_data['name'],
                            'service' : device_data['service'],
                            'assignments': device_data.get('assignments', []),  # Store assignments directly
                        }
                    )

                    if created:
                        print(f"Device {device.name} created for project {project.name}.")
                    else:
                        print(f"Device {device.name} updated for project {project.name}.")

                except Exception as e:
                    print(f"Error while processing device {device_data['name']} for project {project.name}: {str(e)}")

    except Exception as e:
        print(f"Error while syncing devices for project {project.name}: {str(e)}")

# def sync_project_observations(project, batch_size=1000):
#     """Sync observations for the project using optimized grouping."""
#     try:
#         observations_data = fetch_zenus_data(f"projects/{project.id}/observations")

#         if observations_data["observations"]:
#             if "obs" not in project.type:
#                 project.type.append("obs")
#                 project.save()

#             # Temporary lists to store objects for bulk_create and bulk_update
#             observations_to_create = []
#             observations_to_update = []

#             for observation_data in observations_data["observations"]:
#                 try:
#                     parsed_datetime = parser.isoparse(observation_data['datetime'])
#                     parsed_datetime = timezone.make_aware(parsed_datetime)

#                     session = get_session(parsed_datetime, observation_data['device_id'], project, "obs")
#                     if not session:
#                         session = None  # If no session, set to None

#                     # Try to find if the observation already exists
#                     existing_observation = ObservationModel.objects.filter(
#                         session=session,
#                         datetime=parsed_datetime,
#                         project=project
#                     ).first()

#                     if existing_observation:
#                         # If the observation exists, update it
#                         existing_observation.device_id = observation_data['device_id']
#                         existing_observation.device_name = observation_data['device_name']
#                         existing_observation.count_total = observation_data['count_total']
#                         existing_observation.count_male = observation_data['count_male']
#                         existing_observation.count_female = observation_data['count_female']
#                         existing_observation.count_under_40 = observation_data['count_under_40']
#                         existing_observation.count_over_40 = observation_data['count_over_40']
#                         existing_observation.energy = observation_data['energy']
#                         existing_observation.energy_male = observation_data['energy_male']
#                         existing_observation.energy_female = observation_data['energy_female']
#                         existing_observation.energy_under_40 = observation_data['energy_under_40']
#                         existing_observation.energy_over_40 = observation_data['energy_over_40']
#                         observations_to_update.append(existing_observation)
#                     else:
#                         # If the observation does not exist, create a new one
#                         observations_to_create.append(
#                             ObservationModel(
#                                 session=session,
#                                 datetime=parsed_datetime,
#                                 project=project,
#                                 device_id=observation_data['device_id'],
#                                 device_name=observation_data['device_name'],
#                                 count_total=observation_data['count_total'],
#                                 count_male=observation_data['count_male'],
#                                 count_female=observation_data['count_female'],
#                                 count_under_40=observation_data['count_under_40'],
#                                 count_over_40=observation_data['count_over_40'],
#                                 energy=observation_data['energy'],
#                                 energy_male=observation_data['energy_male'],
#                                 energy_female=observation_data['energy_female'],
#                                 energy_under_40=observation_data['energy_under_40'],
#                                 energy_over_40=observation_data['energy_over_40'],
#                             )
#                         )
#                 except Exception as e:
#                     print(f"Error processing observation for device {observation_data['device_id']} at {observation_data['datetime']} for project {project.name}: {str(e)}")
                
#                 # When we reach the batch size limit, bulk insert or update and reset the lists
#                 if len(observations_to_create) >= batch_size or len(observations_to_update) >= batch_size:
#                     with transaction.atomic():
#                         if observations_to_create:
#                             ObservationModel.objects.bulk_create(observations_to_create)
#                         if observations_to_update:
#                             ObservationModel.objects.bulk_update(observations_to_update, [
#                                 'device_id', 'device_name', 'count_total', 'count_male', 'count_female', 
#                                 'count_under_40', 'count_over_40', 'energy', 'energy_male', 'energy_female', 
#                                 'energy_under_40', 'energy_over_40'])

#                     # Reset the lists for the next batch
#                     observations_to_create = []
#                     observations_to_update = []
            
#             # Handle any remaining observations after the loop
#             if observations_to_create or observations_to_update:
#                 with transaction.atomic():
#                     if observations_to_create:
#                         ObservationModel.objects.bulk_create(observations_to_create)
#                     if observations_to_update:
#                         ObservationModel.objects.bulk_update(observations_to_update, [
#                             'device_id', 'device_name', 'count_total', 'count_male', 'count_female', 
#                             'count_under_40', 'count_over_40', 'energy', 'energy_male', 'energy_female', 
#                             'energy_under_40', 'energy_over_40'])

#         print(f"Observations synced for project {project.name}")

#     except Exception as e:
#         print(f"Error while syncing observations for project {project.name}: {str(e)}")

def sync_project_observations(project, batch_size=1000):
    """Sync observations for the project by always creating new records."""
    try:
        observations_data = fetch_zenus_data(f"projects/{project.id}/observations")
        if not observations_data.get("observations"):
            print(f"No observations for project {project.name}")
            return

        # mark project as having obs
        if "obs" not in project.type:
            project.type.append("obs")
            project.save()

        observations_to_create = []

        for obs_data in observations_data["observations"]:
            try:
                dt = parser.isoparse(obs_data["datetime"])
                dt = timezone.make_aware(dt)
                session = get_session(dt, obs_data["device_id"], project, "obs") or None

                # build new model instance
                obs = ObservationModel(
                    session=session,
                    datetime=dt,
                    project=project,
                    device_id=obs_data["device_id"],
                    device_name=obs_data["device_name"],
                    count_total=obs_data["count_total"],
                    count_male=obs_data["count_male"],
                    count_female=obs_data["count_female"],
                    count_under_40=obs_data["count_under_40"],
                    count_over_40=obs_data["count_over_40"],
                    energy=obs_data["energy"],
                    energy_male=obs_data["energy_male"],
                    energy_female=obs_data["energy_female"],
                    energy_under_40=obs_data["energy_under_40"],
                    energy_over_40=obs_data["energy_over_40"],
                )

                observations_to_create.append(obs)
                print(f"lfg Created obs for session={session} at {dt}")

            except Exception as e:
                print(f"Error processing obs {obs_data['device_id']} @ {obs_data['datetime']}: {e}")

            # flush in batches
            if len(observations_to_create) >= batch_size:
                with transaction.atomic():
                    ObservationModel.objects.bulk_create(observations_to_create)
                observations_to_create = []

        # flush any remaining
        if observations_to_create:
            with transaction.atomic():
                ObservationModel.objects.bulk_create(observations_to_create)

        print(f"All observations created for project {project.name}")

    except Exception as e:
        print(f"Error syncing observations for project {project.name}: {e}")



def calculate_and_save_analytics(project):
    """Aggregate observation data and save demographic ratios & energies at the session level, grouped by device_id."""
    sessions = project.sessions.all()  # Get all sessions related to the project

    if not sessions.exists():
        return  # No sessions found, skip processing

    for session in sessions:
        qs = ObservationModel.objects.filter(project=project, session=session)

        if not qs.exists():
            continue  # No observation data for this session; skip

        # Group data by device_id
        device_data = defaultdict(lambda: {
            "sum_total": 0.0,
            "sum_male": 0.0,
            "sum_female": 0.0,
            "sum_under_40": 0.0,
            "sum_over_40": 0.0,
            "weighted_energy": 0.0,
            "weighted_male_energy": 0.0,
            "weighted_female_energy": 0.0,
            "weighted_under_40_energy": 0.0,
            "weighted_over_40_energy": 0.0
        })

        for obs in qs:
            device_id = obs.device_id or "unknown"

            count_total = obs.count_total or 0
            count_male = obs.count_male or 0
            count_female = obs.count_female or 0
            count_under_40 = obs.count_under_40 or 0
            count_over_40 = obs.count_over_40 or 0

            device_data[device_id]["sum_total"] += count_total
            device_data[device_id]["sum_male"] += count_male
            device_data[device_id]["sum_female"] += count_female
            device_data[device_id]["sum_under_40"] += count_under_40
            device_data[device_id]["sum_over_40"] += count_over_40

            # Weighted energy sums
            if count_total and obs.energy is not None:
                device_data[device_id]["weighted_energy"] += count_total * obs.energy
            if count_male and obs.energy_male is not None:
                device_data[device_id]["weighted_male_energy"] += count_male * obs.energy_male
            if count_female and obs.energy_female is not None:
                device_data[device_id]["weighted_female_energy"] += count_female * obs.energy_female
            if count_under_40 and obs.energy_under_40 is not None:
                device_data[device_id]["weighted_under_40_energy"] += count_under_40 * obs.energy_under_40
            if count_over_40 and obs.energy_over_40 is not None:
                device_data[device_id]["weighted_over_40_energy"] += count_over_40 * obs.energy_over_40

        # Aggregate all device-level data to compute final averages per session
        total_devices = len(device_data)
        final_aggregates = defaultdict(float)

        for device_id, data in device_data.items():
            sum_total = data["sum_total"]

            if sum_total > 0:
                final_aggregates["male_ratio"] += (data["sum_male"] / sum_total) / total_devices
                final_aggregates["female_ratio"] += (data["sum_female"] / sum_total) / total_devices
                final_aggregates["under_40_ratio"] += (data["sum_under_40"] / sum_total) / total_devices
                final_aggregates["over_40_ratio"] += (data["sum_over_40"] / sum_total) / total_devices

                final_aggregates["energy_avg"] += (data["weighted_energy"] / sum_total) / total_devices
                final_aggregates["male_energy_avg"] += (data["weighted_male_energy"] / data["sum_male"]) / total_devices if data["sum_male"] > 0 else 0
                final_aggregates["female_energy_avg"] += (data["weighted_female_energy"] / data["sum_female"]) / total_devices if data["sum_female"] > 0 else 0
                final_aggregates["under_40_energy_avg"] += (data["weighted_under_40_energy"] / data["sum_under_40"]) / total_devices if data["sum_under_40"] > 0 else 0
                final_aggregates["over_40_energy_avg"] += (data["weighted_over_40_energy"] / data["sum_over_40"]) / total_devices if data["sum_over_40"] > 0 else 0

        # Save the final aggregated session analytics
        analytics, created = SessionAnalyticsModel.objects.get_or_create(
            project=project, session=session
        )

        analytics.male_ratio = final_aggregates["male_ratio"]
        analytics.female_ratio = final_aggregates["female_ratio"]
        analytics.under_40_ratio = final_aggregates["under_40_ratio"]
        analytics.over_40_ratio = final_aggregates["over_40_ratio"]

        analytics.energy_avg = final_aggregates["energy_avg"]
        analytics.male_energy_avg = final_aggregates["male_energy_avg"]
        analytics.female_energy_avg = final_aggregates["female_energy_avg"]
        analytics.under_40_energy_avg = final_aggregates["under_40_energy_avg"]
        analytics.over_40_energy_avg = final_aggregates["over_40_energy_avg"]

        analytics.save()

        print(f"Session analytics updated for {session.name} in project {project.name}")

def calculate_impression_analytics(project, zone):
    """Calculate and save impression analytics for the given project."""
    try:
        # Check if 'imp' is included in the project's type
        if 'imp' not in project.type:
            print(f"Project {project.name} does not have 'imp' in its type. Skipping analytics calculation.")
            return None
        # Get all impressions for the project
        impressions = ImpressionModel.objects.filter(project=project, zone=zone)

        if not impressions.exists():
            # No impressions found, store default values in the database
            print(f"No impressions found for project {project.name}. Storing default analytics.")
            
            # Create default values for ImpressionAnalyticsModel
            default_analytics_data = {
                "date": [],
                "impression_count": [],
                "total_impressions": 0,
            }

            # Save default record in ImpressionAnalyticsModel
            impression_analytics, created = ImpressionAnalyticsModel.objects.update_or_create(
                project=project,
                zone=zone,
                defaults=default_analytics_data
            )

            action = "created" if created else "updated"
            print(f"Impression analytics {action} for project {project.name} with default values.")
            return impression_analytics  # Return the default analytics object

        # Initialize variables for calculations
        total_impressions = impressions.count()

        # Initialize data structures for the split impression counts
        date_impression_count = defaultdict(list)
        date_list = []

        for impression in impressions:
            latest_datetime = impression.latest_datetime
            date_str = latest_datetime.date().strftime('%Y-%m-%d')

            if date_str not in date_list:
                date_list.append(date_str)

            # Collect impressions by date to calculate the time splits later
            date_impression_count[date_str].append(latest_datetime)

        # Prepare the impression count split by time (dividing the day into 15 parts)
        time_intervals = 15
        split_impression_count = []

        for date_str, impressions_on_date in date_impression_count.items():
            # Sort the impressions to get the first and last impression times for the day
            impressions_on_date.sort()
            first_impression_time = impressions_on_date[0]
            last_impression_time = impressions_on_date[-1]

            # Calculate the total duration in minutes between first and last impression time
            total_duration = (last_impression_time - first_impression_time).total_seconds() / 60  # in minutes

            # Calculate the interval duration
            interval_duration = total_duration / time_intervals  # duration of each interval in minutes

            # Prepare time intervals
            time_split = []
            for i in range(time_intervals):
                start_time = first_impression_time + timedelta(minutes=i * interval_duration)
                end_time = first_impression_time + timedelta(minutes=(i + 1) * interval_duration)
                
                # Count impressions in the current time slot
                count = sum(1 for imp_time in impressions_on_date if start_time <= imp_time <= end_time)
                
                time_split.append({"time": f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}", "count": count})

            split_impression_count.append({"date": date_str, "impression_count": time_split})

        # Create and save ImpressionAnalyticsModel
        impression_analytics, created = ImpressionAnalyticsModel.objects.update_or_create(
            project=project,
            zone=zone,
            defaults={
                "date":date_list,
                "impression_count":split_impression_count,
                "total_impressions":total_impressions,
            }
        )
        action = "created" if created else "updated"
        print(f"Impression analytics {action} for project {project.name}.")
        return impression_analytics

    except Exception as e:
        print(f"Error while processing impression analytics for project {project.name}: {str(e)}")   

# FOR THIS IMPRESSION DATA update_or_create function does not work properly so just used create functino
def sync_project_impressions(project, batch_size=1000):
    """Sync impressions for the project using optimized grouping with batch processing."""
    try:
        impressions_data = fetch_zenus_data(f"projects/{project.id}/impressions")

        if impressions_data["impressions"]:
            if "imp" not in project.type:
                project.type.append("imp")
                project.save()

        impressions_to_create = []
        impressions_to_update = []

        for impression_data in impressions_data["impressions"]:
            try:
                parsed_datetime = parser.isoparse(impression_data['latest_datetime'])
            except ValueError:
                raise ValueError(f"Invalid datetime format for qr_code_data: {impression_data['latest_datetime']}")

            # Convert to timezone-aware datetime if necessary
            parsed_datetime = timezone.make_aware(parsed_datetime)

            booth = get_booth(parsed_datetime, impression_data["device_id"], project)

            # Try to find the existing impression based on `project`, `device_id`, and `latest_datetime`
            existing_impression = ImpressionModel.objects.filter(
                project=project,
                device_id=impression_data["device_id"],
                latest_datetime=parsed_datetime
            ).first()

            if existing_impression:
                # If the impression exists, update it
                existing_impression.device_name = impression_data["device_name"]
                existing_impression.dwell_time = impression_data["dwell_time"]
                existing_impression.energy_median = impression_data["energy_median"]
                existing_impression.face_height_median = impression_data["face_height_median"]
                existing_impression.biological_sex = impression_data["biological_sex"]
                existing_impression.biological_age = impression_data["biological_age"]
                existing_impression.zone = impression_data["zone"]
                existing_impression.booth = booth
                impressions_to_update.append(existing_impression)
            else:
                # If the impression does not exist, create a new one
                impressions_to_create.append(
                    ImpressionModel(
                        project=project,
                        device_id=impression_data["device_id"],
                        latest_datetime=parsed_datetime,
                        device_name=impression_data["device_name"],
                        dwell_time=impression_data["dwell_time"],
                        energy_median=impression_data["energy_median"],
                        face_height_median=impression_data["face_height_median"],
                        biological_sex=impression_data["biological_sex"],
                        biological_age=impression_data["biological_age"],
                        zone=impression_data["zone"],
                        booth=booth
                    )
                )

            # When we reach the batch size limit, bulk insert or update and reset the lists
            if len(impressions_to_create) >= batch_size or len(impressions_to_update) >= batch_size:
                with transaction.atomic():
                    if impressions_to_create:
                        ImpressionModel.objects.bulk_create(impressions_to_create)
                    if impressions_to_update:
                        ImpressionModel.objects.bulk_update(impressions_to_update, [
                            'device_name', 'dwell_time', 'energy_median', 'face_height_median', 
                            'biological_sex', 'biological_age', 'zone', 'booth'])
                
                # Reset the lists for the next batch
                impressions_to_create = []
                impressions_to_update = []

        # Handle any remaining impressions after the loop
        if impressions_to_create or impressions_to_update:
            with transaction.atomic():
                if impressions_to_create:
                    ImpressionModel.objects.bulk_create(impressions_to_create)
                if impressions_to_update:
                    ImpressionModel.objects.bulk_update(impressions_to_update, [
                        'device_name', 'dwell_time', 'energy_median', 'face_height_median', 
                        'biological_sex', 'biological_age', 'zone', 'booth'])

        print(f"Impressions synced for project {project.name}")

    except Exception as e:
        print(f"Error syncing impressions for project {project.name}: {str(e)}")

def sync_project_unique_impressions(project, batch_size=1000):
    """Sync unique impressions for a given project using optimized batching."""
    try:
        impressions_data = fetch_zenus_data(f'projects/{project.id}/unique-impressions')
        
        if impressions_data and 'uniqueImpressions' in impressions_data:
            unique_impressions = impressions_data['uniqueImpressions']
            unique_impressions_to_create = []
            unique_impressions_to_update = []

            for impression_data in unique_impressions:
                try:
                    try:
                        parsed_datetime = parser.isoparse(impression_data['date'])
                    except ValueError:
                        raise ValueError(f"Invalid datetime format for qr_code_data: {impression_data['date']}")

                    # Convert to timezone-aware datetime if necessary
                    parsed_datetime = timezone.make_aware(parsed_datetime)

                    booth = get_booth(parsed_datetime, impression_data['device_id'], project)

                    # Try to find the existing unique impression based on `device_id` and `date`
                    existing_impression = UniqueImpressionModel.objects.filter(
                        project=project,
                        device_id=impression_data['device_id'],
                        date=parsed_datetime,
                        zone=impression_data['zone'],
                        is_staff=impression_data['is_staff'],
                        impressions_total=impression_data['impressions_total'],
                        visit_duration=impression_data['visit_duration'],
                        dwell_time=impression_data['dwell_time'],
                        energy_median=impression_data['energy_median'],
                        face_height_median=impression_data['face_height_median'],
                        biological_sex=impression_data['biological_sex'],
                        biological_age=impression_data['biological_age'],
                        booth=booth
                    ).first()

                    if existing_impression:
                        # If the unique impression exists, update it
                        existing_impression.is_staff = impression_data['is_staff']
                        existing_impression.impressions_total = impression_data['impressions_total']
                        existing_impression.visit_duration = impression_data['visit_duration']
                        existing_impression.dwell_time = impression_data['dwell_time']
                        existing_impression.energy_median = impression_data['energy_median']
                        existing_impression.face_height_median = impression_data['face_height_median']
                        existing_impression.biological_sex = impression_data['biological_sex']
                        existing_impression.biological_age = impression_data['biological_age']
                        existing_impression.booth = booth
                        unique_impressions_to_update.append(existing_impression)
                    else:
                        # If the unique impression does not exist, create a new one
                        unique_impressions_to_create.append(
                            UniqueImpressionModel(
                                project=project,
                                device_id=impression_data['device_id'],
                                date=parsed_datetime,
                                zone=impression_data['zone'],
                                is_staff=impression_data['is_staff'],
                                impressions_total=impression_data['impressions_total'],
                                visit_duration=impression_data['visit_duration'],
                                dwell_time=impression_data['dwell_time'],
                                energy_median=impression_data['energy_median'],
                                face_height_median=impression_data['face_height_median'],
                                biological_sex=impression_data['biological_sex'],
                                biological_age=impression_data['biological_age'],
                                booth=booth
                            )
                        )

                except Exception as e:
                    print(f"Error while processing unique impression for device {impression_data['device_id']} on {impression_data['date']} for project {project.name}: {str(e)}")

                # When we reach the batch size limit, bulk insert or update and reset the lists
                if len(unique_impressions_to_create) >= batch_size or len(unique_impressions_to_update) >= batch_size:
                    with transaction.atomic():
                        if unique_impressions_to_create:
                            UniqueImpressionModel.objects.bulk_create(unique_impressions_to_create)
                        if unique_impressions_to_update:
                            UniqueImpressionModel.objects.bulk_update(unique_impressions_to_update, [
                                'is_staff', 'impressions_total', 'visit_duration', 'dwell_time', 'energy_median', 
                                'face_height_median', 'biological_sex', 'biological_age', 'booth'])

                    # Reset the lists for the next batch
                    unique_impressions_to_create = []
                    unique_impressions_to_update = []

            # Handle any remaining unique impressions after the loop
            if unique_impressions_to_create or unique_impressions_to_update:
                with transaction.atomic():
                    if unique_impressions_to_create:
                        UniqueImpressionModel.objects.bulk_create(unique_impressions_to_create)
                    if unique_impressions_to_update:
                        UniqueImpressionModel.objects.bulk_update(unique_impressions_to_update, [
                            'is_staff', 'impressions_total', 'visit_duration', 'dwell_time', 'energy_median', 
                            'face_height_median', 'biological_sex', 'biological_age', 'booth'])

        print(f"Unique Impressions synced for project {project.name}")

    except Exception as e:
        print(f"Error syncing unique impressions for project {project.name}: {str(e)}")

        
def sync_project_qr_codes(project, batch_size=1000):
    """Sync QR codes for the project using optimized grouping."""
    try:
        qr_codes_data = fetch_zenus_data(f"projects/{project.id}/qr-sessions")

        if qr_codes_data["qr_codes"]:
            if "qr" not in project.type:
                project.type.append("qr")
                project.save()

            qr_codes_to_create = []
            qr_codes_to_update = []

            for qr_code_data in qr_codes_data["qr_codes"]:
                try:
                    parsed_datetime = parser.isoparse(qr_code_data['datetime'])
                    parsed_datetime = timezone.make_aware(parsed_datetime)

                    session = get_session(parsed_datetime, qr_code_data['device_id'], project, "qr")
                    if not session:
                        session = None  # If no session, set to None

                    # Try to find if the QR code already exists
                    existing_qr_code = QrCodeModel.objects.filter(
                        device_id=qr_code_data['device_id'],
                        session=session,
                        datetime=parsed_datetime,
                        qr_code = qr_code_data['qr_code'],
                        project=project
                    ).first()

                    if existing_qr_code:
                        # If the QR code exists, update it
                        existing_qr_code.device_name = qr_code_data['device_name']
                        qr_codes_to_update.append(existing_qr_code)
                    else:
                        # If the QR code does not exist, create a new one
                        qr_codes_to_create.append(
                            QrCodeModel(
                                session=session,
                                project=project,
                                datetime=parsed_datetime,
                                qr_code=qr_code_data['qr_code'],
                                device_id=qr_code_data['device_id'],
                                device_name=qr_code_data['device_name'],
                            )
                        )
                except Exception as e:
                    print(f"Error processing QR code for device {qr_code_data['device_id']} at {qr_code_data['datetime']} for project {project.name}: {str(e)}")
                
                # When we reach the batch size limit, bulk insert or update and reset the lists
                if len(qr_codes_to_create) >= batch_size or len(qr_codes_to_update) >= batch_size:
                    with transaction.atomic():
                        if qr_codes_to_create:
                            QrCodeModel.objects.bulk_create(qr_codes_to_create)
                        if qr_codes_to_update:
                            QrCodeModel.objects.bulk_update(qr_codes_to_update, ['device_id', 'device_name', 'qr_code'])

                    # Reset the lists for the next batch
                    qr_codes_to_create = []
                    qr_codes_to_update = []
            
            # Handle any remaining QR codes after the loop
            if qr_codes_to_create or qr_codes_to_update:
                with transaction.atomic():
                    if qr_codes_to_create:
                        QrCodeModel.objects.bulk_create(qr_codes_to_create)
                    if qr_codes_to_update:
                        QrCodeModel.objects.bulk_update(qr_codes_to_update, ['device_id', 'device_name', 'qr_code'])

        print(f"QR Codes synced for project {project.name}")

    except Exception as e:
        print(f"Error while syncing QR codes for project {project.name}: {str(e)}")


def calculate_qr_code_dwell_time(project):
    """Calculate and save dwell time for QR codes grouped by project, date, and qr_code."""
    try:
        # Fetch all QR codes for the project
        qr_codes = QrCodeModel.objects.filter(project=project).order_by("qr_code", "datetime")

        if not qr_codes.exists():
            print(f"No QR codes found for project {project.name}. Skipping dwell time calculation.")
            return

        # Group QR codes by qr_code and date
        qr_groups = defaultdict(list)
        for qr in qr_codes:
            date_str = qr.datetime.date()
            qr_groups[(qr.qr_code, date_str)].append(qr)

        # Calculate dwell time for each QR code group
        for (qr_identifier, date_str), qr_list in qr_groups.items():
            # Ensure the list is sorted by datetime
            qr_list.sort(key=lambda x: x.datetime)
            
            for i, current_qr in enumerate(qr_list):
                # Find the last scan of the day for this qr_code
                last_qr = qr_list[-1]  # Last occurrence for this qr_code on the date

                if current_qr == last_qr:
                    dwell_time_minutes = 0  # If it's already the last scan, no dwell time
                else:
                    dwell_time_minutes = int((last_qr.datetime - current_qr.datetime).total_seconds() // 60)

                # Update the dwell time in the database
                current_qr.dwell_time = dwell_time_minutes
                current_qr.save()

                print(f"Updated dwell time for QR {qr_identifier} on {date_str}: {dwell_time_minutes} minutes.")
    
    except Exception as e:
        print(f"Error calculating QR dwell time for project {project.name}: {str(e)}")

def calculate_project_qr_codes(project):
    """Calculate the number of unique QR codes for a given project and store it."""
    try:
        unique_qr_count = QrCodeModel.objects.filter(project=project).values("qr_code").distinct().count()
        project.unique_qr_codes = unique_qr_count
        project.save()
        print(f"Updated unique QR code count for project {project.name}: {unique_qr_count}")
    except Exception as e:
        print(f"Error calculating unique QR codes for project {project.name}: {str(e)}")

def get_qr_session(time_slot, project):
    """
    Find the session for a QR code (or observation) based on the datetime 'time_slot'.
    Specifically allows matching if 'time_slot' is within:
    
        session.start_datetime - 30 minutes <= time_slot <= session.end_datetime + 15 minutes
    """
    # Convert time_slot (which might be an ISO string) to an aware datetime
    if isinstance(time_slot, str):
        time_slot = timezone.make_aware(timezone.datetime.fromisoformat(time_slot))
    
    # Get all sessions for this project
    sessions = SessionModel.objects.filter(project=project)
    
    for session in sessions:
        start_with_buffer = session.start_datetime - timedelta(minutes=30)
        end_with_buffer   = session.end_datetime + timedelta(minutes=15)

        if start_with_buffer <= time_slot <= end_with_buffer:
            return session

    # If no session matches, return None
    return None

def get_session(datetime, device_id, project, type):
    """
    Finds the session based on device ID, observation datetime, project, and stage type.
    If no session is found, return None.
    """
    try:
        device = ProjectDeviceModel.objects.get(device_id=device_id, project=project)
    except ProjectDeviceModel.DoesNotExist:
        raise ValueError(f"Device with ID {device_id} not found for project {project.name}")

    relevant_ids = []
    for assignment in device.assignments:
        try:
            parsed_datetime = parser.isoparse(assignment['date'])
            assignment_date = timezone.make_aware(parsed_datetime)
            if assignment['active'] and assignment_date.date() == datetime.date():
                for area in assignment['areas']:
                    if area['type'] == 'stages':
                        relevant_ids.append(area['id'])
        except ValueError:
            pass  # Skip invalid dates

    if not relevant_ids:
        return None

    try:
        session = SessionModel.objects.get(
            project=project,
            project_stage__id__in=relevant_ids,
            start_datetime__lte=datetime,
            end_datetime__gte=datetime
        )
    except SessionModel.DoesNotExist:
        return None  # Return None if session not found
    
    # Get the stage and update the type if needed
    stage = session.project_stage
    if stage.type != type:
        stage.type = type
        stage.save()

    return session

def get_booth(datetime, device_id, project):
    """
    Find the booth associated with the given device and datetime for the specified project.
    
    :param datetime: The datetime of the impression.
    :param device_id: The ID of the device.
    :param project: The project to which the device belongs.
    :return: The associated ProjectBoothModel or None if no booth is found.
    """
    global count
    try:
        device = ProjectDeviceModel.objects.get(device_id=device_id, project=project)
    except ProjectDeviceModel.DoesNotExist:
        return None  # Return None if the device is not found

    relevant_booths = []
    for assignment in device.assignments:
        # Convert assignment's date to datetime for comparison
        try:
            parsed_datetime = parser.isoparse(assignment['date'])
        except ValueError:
            continue  # If assignment date is invalid, skip this assignment

        # Convert to timezone-aware datetime if necessary
        assignment_date = timezone.make_aware(parsed_datetime)

        # Check if the assignment is active and the date matches
        if assignment['active'] and assignment_date.date() == datetime.date():
            # Further check if the areas contain a booth (type 'booths')
            for area in assignment['areas']:
                if area['type'] == 'booths':
                    relevant_booths.append(area['id'])

    if not relevant_booths:
        return None  # Return None if no relevant booths are found

    # Attempt to fetch the booths by their IDs
    booths = ProjectBoothModel.objects.filter(booth_id__in=relevant_booths, project=project)

    if not booths:
        return None  # Return None if no booths are found with the relevant IDs

    # correct_booth = None
    # for booth in booths:
    #     # Loop through the booth's operating hours and check if the booth is active
    #     for operating_hour in booth.operating_hours:
    #         operating_date = timezone.make_aware(parser.isoparse(operating_hour['date']))

    #         # Check if the booth is active and if the datetime falls within the operating hours
    #         if operating_date.date() == datetime.date() and operating_hour['active']:
    #             opening_time = datetime.combine(datetime.date(), timezone.make_aware(datetime.strptime(operating_hour['opening_time'], "%H:%M").time()))
    #             closing_time = datetime.combine(datetime.date(), timezone.make_aware(datetime.strptime(operating_hour['closing_time'], "%H:%M").time()))

    #             # Compare only the time part of the datetime
    #             if opening_time <= datetime <= closing_time:
    #                 correct_booth = booth
    #                 break

    #     if correct_booth:
    #         break
    print("correct_booth")
    # return correct_booth  # Return the booth or None if not found
    return booths[0]