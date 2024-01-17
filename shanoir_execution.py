import json
import argparse
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

if __name__ == '__main__':
    parser = create_arg_parser()
    add_common_arguments(parser)
    add_pipeline_arguments(parser)
    add_configuration_arguments(parser)
    args = parser.parse_args()
    config = shanoir_util.initialize(args)

    with open(args.execution_json) as json_file:
       executions = json.load(json_file)

    for execution in executions:
        print(execution)
        # create execution
        execution = shanoir_util.createExecution(config, execution)

        # check until execution is over
        result = "RUNNING"
        while result != "FINISHED":
            result = shanoir_util.getExecutionStatus(config, execution.identifier)

        # mark as done
        writeInFile(execution)

        # remove from input


        # In case of error, do not stop


#python3 ./shanoir_execution.py -lf /tmp/test.log -u jlouis -d shanoir-ng-nginx -exe ./executions.json


