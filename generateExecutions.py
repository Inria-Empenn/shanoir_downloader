import json
import argparse
import csv
import shanoir_util
from pathlib import Path

# This script is used to transform a json file from VHD cohort (this json file needs itself to be manually generated)
#{"values": [["HD-1","0270006","562500","22/03/2017"],["HD-1","0270006","562501","22/03/2017"], [...]}
# Into a list of executions that will be executed in shanoir
if __name__ == '__main__':
    with open("./IRMHDSHANOIR.txt") as datasetEntries:
        entries = json.load(datasetEntries)["values"]

    # this file is a list of dataset IDs that were not already treated in the executions
    with open("./not_done.txt") as dataset_not_done:
        not_done = json.load(dataset_not_done)

    # Here we group datasets by examination and group examination by 4
    examinations = [[]]
    i = 0
    j = 0
    examSize = 4
    currentExamDate = entries[0][3]

    for entry in entries:
        examDate = entry[3]
        if examDate == currentExamDate:
            if entry[2] in not_done:
                examinations[i].append(entry[2])
        else:
            if j < examSize:
                if entry[2] in not_done:
                    currentExamDate = entry[3]
                    examinations[i].append(entry[2])
                    j = j + 1
            else:
                currentExamDate = entry[3]
                i = i + 1
                j = 0
                examinations.append([])
                examinations[i].append(entry[2])

    # Roll over examinations to generation executions
    executions = []
    identifier = 0
    for examination in examinations:
        execution = {
            "identifier" : identifier,
            "name": "OFSEP_sequence_identification",
            "pipelineIdentifier": "ofsep_sequences_identification/0.2",
            "outputProcessing": "",
            "processingType":  "SEGMENTATION",
            "parametersRessources": [
                {"datasetIds": examination,
                 "groupBy": "EXAMINATION",
                 "parameter": "dicom_archive"}]
        }
        executions.append(execution)
        identifier = identifier + 1

    f = open("executions.json", "a")
    f.write(json.dumps(executions))
    f.close()