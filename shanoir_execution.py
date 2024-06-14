import json
import argparse
import logging
import os
import time
from datetime import datetime

import shanoir_util
from pathlib import Path
Path.ls = lambda x: sorted(list(x.iterdir()))

def create_arg_parser(description="""Shanoir downloader"""):
    parser = argparse.ArgumentParser(prog=__file__, description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    return parser

def add_username_argument(parser):
    parser.add_argument('-u', '--username', required=True, help='Your shanoir username.')

def add_domain_argument(parser):
    parser.add_argument('-d', '--domain', default='shanoir.irisa.fr', help='The shanoir domain to query.')

def add_common_arguments(parser):
    add_username_argument(parser)
    add_domain_argument(parser)

def add_configuration_arguments(parser):
    parser.add_argument('-c', '--configuration_folder', required=False, help='Path to the configuration folder containing proxy.properties (Tries to use ~/.su_vX.X.X/ by default). You can also use --proxy_url to configure the proxy (in which case the proxy.properties file will be ignored).')
    parser.add_argument('-pu', '--proxy_url', required=False, help='The proxy url in the format "user@host:port". The proxy password will be asked in the terminal. See --configuration_folder.')
    parser.add_argument('-ca', '--certificate', default='', required=False, help='Path to the CA bundle to use.')
    parser.add_argument('-v', '--verbose', default=False, action='store_true', help='Print log messages.')
    parser.add_argument('-t', '--timeout', type=float, default=60*4, help='The request timeout.')
    parser.add_argument('-lf', '--log_file', type=str, help="Path to the log file. Default is output_folder/downloads.log", default=None)
    return parser

def add_pipeline_arguments(parser):
    parser.add_argument('-exe', '--execution_json', required=True, default='', help='path to the json structure of the executions in a json file')
    return parser

def markAsDone(done_list):
    done_file = open("./done.txt", "w+")
    done_file.write(json.dumps(done_list))
    done_file.close()

def markAsFailed(failed_list):
    failed_file = open("./failed.txt", "w+")
    failed_file.write(json.dumps(failed_list))
    failed_file.close()

def markAsTreated(treated_list):
    treated_file = open('./treated.txt', "w+")
    treated_file.write(json.dumps(treated_list))
    treated_file.close()

def createExecution(config, execution):
    current_identifier = str(execution["identifier"])
    failed = []
    if os.path.isfile("./failed.txt") and os.access("./failed.txt", os.R_OK) and os.path.getsize("./failed.txt") > 0:
        failed_file = open("./failed.txt", "rt+")
        failed = json.load(failed_file)
    else:
        failed_file = open("./failed.txt", "w+")

    failed_file.close()

    done = []
    if os.path.isfile("./done.txt") and os.access("./done.txt", os.R_OK) and os.path.getsize("./done.txt") > 0:
        done_file = open("./done.txt", "rt+")
        done = json.load(done_file)
    else:
        done_file = open("./done.txt", "w+")
    done_file.close()
    result = 'Running'
    # create execution
    delay = 1
    error_or_start = True
    while error_or_start:
        try:
            created_execution = shanoir_util.createExecution(config, execution)
            if created_execution == "401":
                result = 'Forbidden'
            error_or_start = False
        except Exception as exception:

            logging.error("Error during execution's creation, retrying after " + str(delay) + " seconds. "
                          + str(exception))
            time.sleep(delay)
            # Set a extensive delay, 2, 4, 8 , 16, 32, 1mn, 2mn, 4mn, 8mn, 16mn, 32mn and then stop
            if delay < 1025:
                delay = delay + delay

    if result == "Running":
        logging.info("Execution creation success: " + str(created_execution["identifier"]) + ". Waiting for result.")

    # check until execution is over (either finished or in error)
    while result == 'Running':
        logging.info(".")
        delay = 1
        error_or_start = True
        while error_or_start:
            try:
                result_not_string = shanoir_util.getExecutionStatus(config, created_execution["identifier"])
                error_or_start = False
            except Exception as exception:
                logging.error("Error during execution's status retrieval, retrying after " + str(delay) + " seconds. "
                              + str(exception))
                time.sleep(delay)
                # Set a extensive delay, 2, 4, 8 , 16, 32, 1mn, 2mn, 4mn, 8mn, 16mn, 32mn and then stop
                if delay < 1025:
                    delay = delay + delay

        result = result_not_string.decode()
        if result == 'Running':
            time.sleep(30)

    if result == 'Finished':
        # Mark as done
        logging.info("Success: " + str(created_execution["identifier"]))
        done.append(current_identifier)
        markAsDone(done)
    else:
        # Mark as failed
        logging.info("Error: " + str(result) + " : " + str(created_execution["identifier"] if result != "Forbidden" else current_identifier))
        failed.append(current_identifier)
        markAsFailed(failed)

if __name__ == '__main__':
    parser = create_arg_parser()
    add_common_arguments(parser)
    add_pipeline_arguments(parser)
    add_configuration_arguments(parser)
    args = parser.parse_args()
    config = shanoir_util.initialize(args)

    with open(args.execution_json) as json_file:
        executions = json.load(json_file)

    count = 0
    treated = []

    if os.path.isfile("./treated.txt") and os.access("./treated.txt", os.R_OK) and os.path.getsize("./treated.txt") > 0:
        treatedFile = open("./treated.txt", "rt+")
        treated = json.load(treatedFile)
    else:
        treatedFile = open("./treated.txt", "w+")

    treatedFile.close()

    for execution in executions:
        if 1 < datetime.now().hour < 4:
            # Wait for 4 hours between 1 and 5 in the morning to avoid errors.
            time.sleep(14400)
        identifier = str(execution["identifier"])
        if identifier not in treated:
            logging.info("Creating execution " + str(count) + " of " + str(len(executions)))
            treated.append(identifier)
            markAsTreated(treated)
            createExecution(config, execution)
        else:
            logging.info("Execution " + str(identifier) + " already treated, skipping..")
        count = count + 1

#python3 ./shanoir_execution.py -lf /tmp/test.log -u XXXX -d shanoir-ng-nginx -exe ./executions.json
#python3 ./shanoir_execution.py -lf /tmp/test.log -u XXXX -d shanoir-ofsep-qualif.irisa.fr -exe ./executions.json