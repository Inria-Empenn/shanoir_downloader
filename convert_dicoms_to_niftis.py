import zipfile
import logging
import shutil
from pathlib import Path
import pandas
import dicom2nifti
import SimpleITK as sitk
import shanoir_downloader
from anima_utils import *

def save_conversion_tools(conversion_info_path, conversion_info):
    df = pandas.DataFrame.from_records(conversion_info)
    df.to_csv(conversion_info_path, sep='\t', index=False)
    return

def get_first_nifti(path):
    niftis = list(Path(path).glob('**/*.nii.gz'))
    return niftis[0] if len(niftis) > 0 else None

def image_is_readable(image_path):
    if image_path is None: return None
    try:
        return sitk.ReadImage(str(image_path))
    except:
        return None

def simple_itk_conversion(folder_path, output_path):
    reader = sitk.ImageSeriesReader()
    reader.SetMetaDataDictionaryArrayUpdate(True)
    reader.SetFileNames(reader.GetGDCMSeriesFileNames(str(folder_path)))
    image = reader.Execute()
    sitk.WriteImage(image, output_path / f'{output_path.name}.nii.gz')
    return

def convert_dicom_to_nifti(dicom_directory, output_folder):
    output_folder.mkdir(parents=True, exist_ok=True)

    image_converted = False
    
    simple_itk_command = lambda: simple_itk_conversion(dicom_folder, output_folder)
    dicom2nifti_command = lambda: dicom2nifti.convert_directory(dicom_directory, output_folder, compression=True, reorient=True)
    mricron_dcm2niix_command = lambda: call(['/data/amasson/apps/dcm2nii/mricron/dcm2niix', '-z', 'y', '-w', '1', '-o', output_folder, dicom_directory])
    dcm2niix_command = lambda: call(['dcm2niix', '-z', 'y', '-o', output_folder, dicom_directory])
    mcverter_command = lambda: call(['mcverter', '-o', output_folder, '-f', 'nifti', '-n', dicom_directory])

    # commands = [mcverter_command]
    commands = [dcm2niix_command, dicom2nifti_command, simple_itk_command, mcverter_command, mricron_dcm2niix_command]
    commandNames = ['dcm2niix', 'dicom2nifti', 'simple_itk', 'mcverter', 'mricronDcm2niix']
    # commands = [dicom2nifti_command, mricron_dcm2niix_command, dcm2niix_command, mcverter_command]
    # commandNames = ['dicom2nifti', 'mcverter', 'dcm2niix', 'mricronDcm2niix']

    conversion_tool = None
    reconverted = None
    image_converted = None

    for i, command in enumerate(commands):
        conversion_tool = commandNames[i]
        print(f'Convert using {conversion_tool}...')
        reconverted = False
        try:
            command()
        except:
            pass
        image_path = get_first_nifti(output_folder)
        if image_path is None: continue
        image_converted = image_is_readable(image_path)
        if image_converted is not None: break
        print(f'Image could not be opened, trying animaConvertImage...')
        call([animaConvertImage, '-i', image_path, '-o', image_path])
        reconverted = True
        image_converted = image_is_readable(image_path)
        if image_converted is not None: break
        print(f'Image could not be opened, even after animaConvertImage...')
    
    if image_converted is not None:
        print(f'Image was successfully converted by {conversion_tool} {"and" if reconverted else "without"} animaConvertImage...')
    else:
        print(f'Image could not be converted by any converter {commandNames}...')

    return conversion_tool, reconverted, image_converted

def convert_dicom_to_nifti_if_needed(dicom_directory, output_folder, keep_dicom, conversion_info_path, conversion_info):

    if str(dicom_directory) in [ci['path'] for ci in conversion_info]:
        return output_folder, None
    
    conversion_tool, reconverted, image_converted = convert_dicom_to_nifti(dicom_directory, output_folder)

    if not keep_dicom:
        if image_converted is not None:
            shutil.rmtree(str(dicom_directory))
        else:
            print('ERROR: dicom could not be converted!', dicom_directory)

    conversion_info.append({'path': str(dicom_directory), 'conversion_tool': conversion_tool, 'reconverted': reconverted, 'converted': image_converted is not None})
    save_conversion_tools(conversion_info_path, conversion_info)

    return output_folder, image_converted

if __name__ == "__main__":
    
    parser = shanoir_downloader.create_arg_parser("Convert DICOMs to Niftis")

    parser.add_argument('-d', '--dicoms', required=True, help='Path to the folder containing the dicoms (raw/). Each zipped dicom (.zip) of dicom sequence (folder) must be in its own folder.')
    parser.add_argument('-ff', '--from_folders', default=False, action='store_true', help='Convert from folders instead of zip archives.')
    parser.add_argument('-of', '--output_folder', required=False, help='Path to the output folder (only used when using --from_folders).')
    parser.add_argument('-kd', '--keep_dicom', default=False, action='store_true', help='Keep dicoms after conversion.')
    parser.add_argument('-ow', '--overwrite', default=False, action='store_true', help='Overwrite the nifti if it exists.')

    args = parser.parse_args()

    dicoms = Path(args.dicoms)

    conversion_info = []
    conversion_info_path = dicoms / 'conversion_info.tsv'

    if conversion_info_path.exists():
        df = pandas.read_csv(conversion_info_path, sep='\t', index_col=False)
        conversion_info = df.to_dict('records')

    for dicom in sorted(list(dicoms.iterdir())):
        if args.from_folders:
            if dicom.suffix == '.zip': continue
            print('Converting', dicom)
            convert_dicom_to_nifti_if_needed(dicom, Path(args.output_folder) / f'{dicom.name}', args.keep_dicom, conversion_info_path, conversion_info)
        else:
            # Extract the zip file
            nifti = get_first_nifti(dicom)
            if not args.overwrite and nifti is not None: continue
            zip_files = list(dicom.glob('**/*.zip'))
            for dicom_zip in zip_files:
                print(dicom_zip)
                logging.info(f'    Extracting {dicom_zip}...')
                dicom_folder = dicom_zip.parent / dicom_zip.stem
                dicom_folder.mkdir(exist_ok=True)
                with zipfile.ZipFile(str(dicom_zip), 'r') as zip_ref:
                    zip_ref.extractall(str(dicom_folder))
                convert_dicom_to_nifti_if_needed(dicom_folder, dicom_folder.parent, args.keep_dicom, conversion_info_path, conversion_info)
    