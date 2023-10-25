import sys
import os
import configparser as ConfParser
import subprocess
from pathlib import Path
Path.ls = lambda x: list(x.iterdir())

configFilePath = os.path.expanduser("~") + "/.anima/config.txt"
if not os.path.exists(configFilePath):
    print('Please create a configuration file for Anima python scripts. Refer to the README')
    quit()

configParser = ConfParser.RawConfigParser()
configParser.read(configFilePath)

animaDir = Path(configParser.get("anima-scripts", 'anima'))
animaScriptPublicDir = Path(configParser.get("anima-scripts", 'anima-scripts-public-root'))
animaExtraDataDir = Path(configParser.get("anima-scripts", 'extra-data-root'))

# Anima commands
animaPyramidalBMRegistration = animaDir / "animaPyramidalBMRegistration"
animaMaskImage = animaDir / "animaMaskImage"
animaNLMeans = animaDir / "animaNLMeans"
animaN4BiasCorrection = animaDir / "animaN4BiasCorrection"
animaConvertImage = animaDir / "animaConvertImage"
animaApplyTransformSerie = animaDir / "animaApplyTransformSerie"
animaTransformSerieXmlGenerator = animaDir / "animaTransformSerieXmlGenerator"
animaDenseSVFBMRegistration = animaDir / "animaDenseSVFBMRegistration"
animaMorphologicalOperations = animaDir / "animaMorphologicalOperations"
animaNyulStandardization = animaDir / "animaNyulStandardization"
animaImageResolutionChanger = animaDir / "animaImageResolutionChanger"
animaConnectedComponents = animaDir / "animaConnectedComponents"
animaCropImage = animaDir / "animaCropImage"
animaLinearTransformArithmetic = animaDir / "animaLinearTransformArithmetic"
animaImageArithmetic = animaDir / "animaImageArithmetic"
animaDisplacementFieldJacobian = animaDir / "animaDisplacementFieldJacobian"
animaBrainExtraction = animaScriptPublicDir / "brain_extraction" / "animaAtlasBasedBrainExtraction.py"

template_directory = animaExtraDataDir / 'ms-study-atlas'
template_flair = template_directory / 'FLAIR/FLAIR_1.nrrd'

def get_registration_options_from_image(refImage):

    # Decide on whether to use large image setting or small image setting
    command = [animaConvertImage, "-i", refImage, "-I"]
    convert_output = subprocess.check_output(command, universal_newlines=True)
    size_info = convert_output.split('\n')[1].split('[')[1].split(']')[0]
    large_image = False
    for i in range(0, 3):
        size_tmp = int(size_info.split(', ')[i])
        if size_tmp >= 350:
            large_image = True
            break

    pyramid_options = ["-p", "4", "-l", "1"]
    if large_image:
        pyramid_options = ["-p", "6", "-l", "3"]
    return pyramid_options

# Calls a command, if there are errors: outputs them and exit
def call(command, stdout=subprocess.DEVNULL):
    command = [str(arg) for arg in command]
    status = subprocess.call(command, stdout=stdout)
    if status != 0:
        print(' '.join(command) + '\n')
        raise Exception('Command exited with status: ' + str(status), status)
        # sys.exit('Command exited with status: ' + str(status))
    return status
