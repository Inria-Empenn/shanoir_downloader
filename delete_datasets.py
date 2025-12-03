import json
import argparse
import logging
import os
import time
import sys
from datetime import datetime

import shanoir_util
from pathlib import Path
Path.ls = lambda x: sorted(list(x.iterdir()))

def create_arg_parser(description="""Shanoir deletion"""):
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

def add_deletion_arguments(parser):
    parser.add_argument('-dids', '--dataset_ids', default='', help='Path to a file containing the dataset ids to delete (a .txt file containing one dataset id per line).')
    return parser

if __name__ == '__main__':
    parser = create_arg_parser()
    add_common_arguments(parser)
    add_deletion_arguments(parser)
    add_configuration_arguments(parser)
    args = parser.parse_args()
    config = shanoir_util.initialize(args)

    SHANOIR_SHUTDOWN_HOUR = 2
    SHANOIR_AVAILABLE_HOUR = 5

    # Get dataset Ids file
    dataset_ids = Path(args.dataset_ids) if args.dataset_ids else None
    if args.dataset_ids and not dataset_ids.exists():
        sys.exit('Error: given file does not exist: ' + str(dataset_ids))

    if dataset_ids:
        with open(dataset_ids) as file:
            dataset_id_list = [dataset_id.strip() for dataset_id in file]

            for dataset_id in dataset_id_list:
                now = datetime.now()
                if now.hour >= SHANOIR_SHUTDOWN_HOUR and now.hour < SHANOIR_AVAILABLE_HOUR:
                    future = datetime(now.year, now.month, now.day, SHANOIR_AVAILABLE_HOUR, 0)
                    time.sleep((future-now).total_seconds())
                result = shanoir_util.deleteDataset(config, dataset_id)
                if result == 204:
                    logging.info("Dataset " + dataset_id + " deleted with success.")
                else:
                    logging.error("Dataset " + dataset_id + ": Error during deletion " + str(result))
                time.sleep(1)

#python3 ./delete_datasets.py -lf /tmp/test.log -u XXXX -d shanoir-ng-nginx -dids ./datasets.txt
