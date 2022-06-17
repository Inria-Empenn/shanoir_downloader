import SimpleITK as sitk
import numpy as np
import argparse
from PIL import Image
from pathlib import Path
Path.ls = lambda x: sorted(list(x.iterdir()))

parser = argparse.ArgumentParser(
    prog=__file__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description="""Create nifti previews""")

parser.add_argument('-d', '--data', required=True, help='Path to the directory containing the niftis.')
parser.add_argument('-o', '--output', default=None, help='Path to the destination directory. Defaults to the same directory as the input directory.')
parser.add_argument('-s', '--slice_spacing', default=5, help='The number of slices per preview image (default = 5, meaning it will save 1 slice every 5 slices).')
parser.add_argument('-n', '--bounding_box_size', default=200, help='Number of frames to consider for the preview bounding box (images are resampled on 0.5x0.5x0.5 mm).')
parser.add_argument('-m', '--mosaic_spacing', default=5, help='Number of preview images in mosaic.')

args = parser.parse_args()

niftis = Path(args.data)
destinationDirectory = Path(args.data) if args.output is None else Path(args.output)
destinationDirectory.mkdir(parents=True, exist_ok=True)
sliceSpacing = int(args.slice_spacing)
boundingBoxSize = int(args.bounding_box_size)
mosaicSpacing = int(args.mosaic_spacing) - 1

planeNames = ['axial', 'coronal', 'sagittal']

def saveImage(image, path, flipX=False, flipY=False):
    pillowImage = Image.fromarray( image.astype(np.uint8) )
    if flipX:
        pillowImage = pillowImage.transpose(Image.FLIP_LEFT_RIGHT)
    if flipY:
        pillowImage = pillowImage.transpose(Image.FLIP_TOP_BOTTOM)
    # print('save image ', path, ' of size ', pillowImage.size)
    pillowImage.save(path, format='png')
    return path

def saveSlicesAt(imageToDisplay, path, n, sizes=None, prefix=''):
    shape = imageToDisplay.shape
    center = [shape[0] // 2, shape[1] // 2, shape[2] // 2]
    halfBoundingBoxSize = boundingBoxSize//2
    image1 = imageToDisplay[max(0, min(center[0] + n, shape[0]-1)), :, :]
    image2 = imageToDisplay[:, max(0, min(center[1] + n, shape[1]-1)), :]
    image3 = imageToDisplay[:, :, max(0, min(center[2] + n, shape[2]-1))]
    flips = [(False, True), (False, True), (True, True)]
    paths = []
    for i, image in enumerate([image1, image2, image3]):
        imagePath = path / (prefix + planeNames[i] + '_' + str(n + halfBoundingBoxSize) + '.png')
        paths.append(imagePath)
        saveImage(image, str(imagePath), flips[i][0], flips[i][1])
    return paths

def saveSlices(imageToDisplay, path, sizes=None, prefix=''):
    halfBoundingBoxSize = boundingBoxSize//2
    paths = []
    if sliceSpacing > 0:
        for n in range(-halfBoundingBoxSize, halfBoundingBoxSize+1, sliceSpacing):
            paths.append(saveSlicesAt(imageToDisplay, path, n, sizes, prefix))
    paths.append(saveSlicesAt(imageToDisplay, path, 0, sizes, f'{prefix}center_'))
    return paths

def createMosaic(imagePaths, previewPath, prefix=''):
    mosaicV = None
    mosaicH = None
    topV = 0
    leftH = 0

    for i in range(0, len(imagePaths), len(imagePaths) // mosaicSpacing):
        slicePaths = imagePaths[i]
        leftV = 0
        topH = 0
        for path in slicePaths:
            image = Image.open(str(path))
            if mosaicV is None:
                mosaicV = image
                mosaicH = image
            else:
                mosaicVWidth = mosaicV.size[0] + image.size[0] if topV == 0 else mosaicV.size[0]
                mosaicVHeight = mosaicV.size[1] + image.size[1] if leftV == 0 else mosaicV.size[1]
                newMosaicV = Image.new('L', (mosaicVWidth, mosaicVHeight))
                newMosaicV.paste(mosaicV, (0, 0, mosaicV.size[0], mosaicV.size[1]))
                box = (leftV, topV, leftV + image.size[0], topV + image.size[1])
                newMosaicV.paste(image, box)
                mosaicV = newMosaicV

                mosaicHWidth = mosaicH.size[0] + image.size[0] if topH == 0 else max(mosaicH.size[0], leftH + image.size[0])
                mosaicHHeight = mosaicH.size[1] + image.size[1] if leftH == 0 else mosaicH.size[1]
                newMosaicH = Image.new('L', (mosaicHWidth, mosaicHHeight))
                newMosaicH.paste(mosaicH, (0, 0, mosaicH.size[0], mosaicH.size[1]))
                box = (leftH, topH, leftH + image.size[0], topH + image.size[1])
                newMosaicH.paste(image, box)
                mosaicH = newMosaicH

            leftV += image.size[0]
            topH += image.size[1]
        topV = mosaicV.size[1]
        leftH = mosaicH.size[0]
    mosaicV.save(str(previewPath / f'{prefix}mosaicV.png'), format='png')
    mosaicH.save(str(previewPath / f'{prefix}mosaicH.png'), format='png')
    return

resampler = sitk.ResampleImageFilter()
newSpacing = (0.5, 0.5, 0.5)

for patientPath in niftis.ls():
    
    if not patientPath.is_dir(): continue

    print(patientPath.name)

    niftiPaths = sorted(list(patientPath.glob('**/*.nii.gz')))

    for niftiPath in niftiPaths:
        
        nifti = sitk.ReadImage(str(niftiPath))
        
        size = nifti.GetSize()
        spacing = nifti.GetSpacing()
        resampler.SetSize([ int(size[0] * spacing[0] / newSpacing[0]), int(size[1] * spacing[1] / newSpacing[1]), int(size[2] * spacing[2] / newSpacing[2]) ])
        resampler.SetOutputSpacing(newSpacing)
        resampler.SetOutputOrigin(nifti.GetOrigin())
        resampler.SetOutputDirection(nifti.GetDirection())
        resampler.SetInterpolator(sitk.sitkLinear)
        result = resampler.Execute(nifti)

        niftiData = sitk.GetArrayFromImage(result)
        minValue = np.min(niftiData)
        maxValue = np.max(niftiData)
        if maxValue > minValue:
            niftiData = (255.0 * (niftiData - minValue)) / float(maxValue - minValue)
        imagePaths = saveSlices(niftiData, destinationDirectory, prefix = niftiPath.parent.name + niftiPath.name)

        if mosaicSpacing > 0:
            createMosaic(imagePaths, destinationDirectory, prefix = niftiPath.parent.name + niftiPath.name)
