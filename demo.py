# Combined code from region_lookup.py, health_client.py, and main.py

# Imports from all files
import dns.resolver
import boto3
import datetime
import logging

# Configure logging (from main.py)
logging.basicConfig(level=logging.INFO)

# Exception from region_lookup.py
class RegionLookupError(Exception):
    """Rasied when there was a problem when looking up the active region"""
    pass

# Function from region_lookup.py
def active_region():
    qname = 'global.health.amazonaws.com'
    try:
        answers = dns.resolver.resolve(qname, 'CNAME')
    except Exception as e:
        raise RegionLookupError('Failed to resolve {}'.format(qname), e)
    if len(answers) != 1:
        raise RegionLookupError('Failed to get a single answer when resolving {}'.format(qname))
    name = str(answers[0].target) # e.g. health.us-east-1.amazonaws.com.
    region_name = name.split('.')[1] # Region name is the 1st in split('.') -> ['health', 'us-east-1', 'amazonaws', 'com', '']
    return region_name

# Exception from health_client.py
class ActiveRegionHasChangedError(Exception):
    """Rasied when the active region has changed"""
    pass

# Class from health_client.py
class HealthClient:
    __active_region = None
    __client = None

    @staticmethod
    def client():
        if not HealthClient.__active_region:
            HealthClient.__active_region = active_region()
        else:
            current_active_region = active_region()
            if current_active_region != HealthClient.__active_region:
                old_active_region = HealthClient.__active_region
                HealthClient.__active_region = current_active_region

                if HealthClient.__client:
                    HealthClient.__client = None

                raise ActiveRegionHasChangedError('Active region has changed from [' + old_active_region + '] to [' + current_active_region + ']')

        if not HealthClient.__client:
            HealthClient.__client = boto3.client('health', region_name=HealthClient.__active_region)

        return HealthClient.__client

# Functions from main.py
def event_details(event):
    # NOTE: It is more efficient to call describe_event_details with a batch
    # of eventArns, but for simplicitly of this demo we call it with a
    # single eventArn
    event_details_response = HealthClient.client().describe_event_details(eventArns=[event['arn']])
    for event_details in event_details_response['successfulSet']:
        logging.info('Details: %s, description: %s', event_details['event'], event_details['eventDescription'])

def describe_events():
    events_paginator = HealthClient.client().get_paginator('describe_events')

    # Describe events using the same default filters as the Personal Health
    # Dashboard (PHD). i.e
    #
    # Return all open or upcoming events which started in the last 7 days,
    # ordered by event lastUpdatedTime

    events_pages = events_paginator.paginate(filter={
        'startTimes': [
            {
                'from': datetime.datetime.now() - datetime.timedelta(days=7)
            }
        ],
        'eventStatusCodes': ['open', 'upcoming']
    })

    number_of_matching_events = 0
    for events_page in events_pages:
        for event in events_page['events']: # This was correct in original main.py
            number_of_matching_events += 1
            event_details(event)

    if number_of_matching_events == 0:
        logging.info('There are no AWS Health events that match the given filters')

# Main execution block from main.py
# If the active endpoint changes we recommend you restart any workflows.
#
# In this sample code we throw an exception if the active endpoint changes in
# the middle of a workflow and restart the workflow using the new active
# endpoint.
restart_workflow = True

while restart_workflow:
    try:
        describe_events()
        restart_workflow = False
    except ActiveRegionHasChangedError as are:
        logging.info("The AWS Health API active region has changed. Restarting the workflow using the new active region!, %s", are)
    except RegionLookupError as rle: # Added handling for RegionLookupError
        logging.error("Error looking up active region: %s", rle)
        restart_workflow = False # Exit loop on lookup error
