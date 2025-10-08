import numpy as np
import random
import unittest
from enum import Enum, auto
import cv2
import os
import tifffile

class CropMethod(Enum):
    RAND = auto()
    CENTER = auto()

def img_path_to_np_flt(fpath):
    '''returns a numpy float32 array from RGB image path (8-16 bits per component)
    shape: c, y, x
    FROM common.libimgops'''
    if not os.path.isfile(fpath):
        raise FileNotFoundError(fpath)

    # For TIFF files, use tifffile (handles floating-point TIFFs from darktable)
    if fpath.lower().endswith(('.tif', '.tiff')):
        try:
            img = tifffile.imread(fpath)
            # tifffile returns RGB already (not BGR like OpenCV)
            # Handle different shapes: (H,W,C) or (C,H,W)
            if img.ndim == 3:
                if img.shape[2] in (3, 4):  # (H, W, C) format
                    rgb_img = img[:, :, :3].transpose(2, 0, 1)  # Take RGB, ignore alpha if present
                elif img.shape[0] in (3, 4):  # (C, H, W) format
                    rgb_img = img[:3, :, :]  # Take RGB channels only
                else:
                    raise ValueError(f'Unexpected TIFF shape: {img.shape}')
            else:
                raise ValueError(f'Expected 3D image, got shape: {img.shape}')
        except Exception as e:
            raise IOError(f'Failed to read TIFF {fpath}: {e}')
    else:
        # Use OpenCV for non-TIFF formats (JPG, PNG, etc.)
        img = cv2.imread(fpath, flags=cv2.IMREAD_COLOR + cv2.IMREAD_ANYDEPTH)
        if img is None:
            raise IOError(f'OpenCV failed to read {fpath}')
        try:
            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)
        except cv2.error as e:
            raise IOError(f'OpenCV error reading {fpath}: {e}')

    # Normalize to [0, 1] float32 based on dtype
    if rgb_img.dtype in (np.float16, np.float32, np.float64):
        return rgb_img.astype(np.float32)
    if rgb_img.dtype == np.uint8:
        return rgb_img.astype(np.float32) / 255.0
    if rgb_img.dtype == np.uint16:
        return rgb_img.astype(np.float32) / 65535.0
    
    raise TypeError(f'img_path_to_np_flt: Error: fpath={fpath} has unknown format ({rgb_img.dtype})')

def extract_icc_profile(fpath):
    '''Extract ICC profile from TIFF file if present'''
    if fpath.lower().endswith(('.tif', '.tiff')):
        try:
            with tifffile.TiffFile(fpath) as tif:
                page = tif.pages[0]
                if 34675 in page.tags:  # ICC Profile tag
                    return page.tags[34675].value
        except:
            pass
    return None

def np_pad_img_pair(img1, img2, cs):
    xpad0 = max(0, (cs - img1.shape[2]) // 2)
    xpad1 = max(0, cs - img1.shape[2] - xpad0)
    ypad0 = max(0, (cs - img1.shape[1]) // 2)
    ypad1 = max(0, cs - img1.shape[1] - ypad0)
    padding = ((0, 0), (ypad0, ypad1), (xpad0, xpad1))
    return np.pad(img1, padding), np.pad(img2, padding)

def np_crop_img_pair(img1, img2, cs: int, crop_method=CropMethod.RAND):
    '''
    crop an image pair into cs
    also compatible with pytorch tensors
    '''
    if crop_method is CropMethod.RAND:
        x0 = random.randint(0, img1.shape[2]-cs)
        y0 = random.randint(0, img1.shape[1]-cs)
    elif crop_method is CropMethod.CENTER:
        x0 = (img1.shape[2]-cs)//2
        y0 = (img1.shape[1]-cs)//2
    return img1[:, y0:y0+cs, x0:x0+cs], img2[:, y0:y0+cs, x0:x0+cs]


class TestImgOps(unittest.TestCase):
    def setUp(self):
        self.imgeven1 = np.random.rand(3, 8, 8)
        self.imgeven2 = np.random.rand(3, 8, 8)
        self.imgodd1 = np.random.rand(3, 5, 5)
        self.imgodd2 = np.random.rand(3, 5, 5)

    def test_pad(self):
        imgeven1_padded, imgeven2_padded = np_pad_img_pair(self.imgeven1, self.imgeven2, 16)
        imgodd1_padded, imgodd2_padded = np_pad_img_pair(self.imgodd1, self.imgodd2, 16)
        self.assertTupleEqual(imgeven1_padded.shape, (3, 16, 16), imgeven1_padded.shape)
        self.assertTupleEqual(imgodd2_padded.shape, (3, 16, 16), imgodd2_padded.shape)
        self.assertEqual(imgeven1_padded[0, 4, 4], self.imgeven1[0, 0, 0])

    def test_crop(self):
        # random crop: check size
        imgeven1_randcropped, imgeven2_randcropped = np_crop_img_pair(self.imgeven1, self.imgeven2, 4, CropMethod.RAND)
        self.assertTupleEqual(imgeven1_randcropped.shape, (3, 4, 4), imgeven1_randcropped.shape)

        # center crop: check size and value
        imgeven1_centercropped, imgeven2_centercropped = np_crop_img_pair(self.imgeven1, self.imgeven2, 4, CropMethod.CENTER)
        self.assertTupleEqual(imgeven1_centercropped.shape, (3, 4, 4), imgeven1_centercropped.shape)
        # orig:    0 1 2 3 4 5 6 7
        # cropped: x x 2 3 4 5 x x
        self.assertEqual(imgeven1_centercropped[0, 0, 0], self.imgeven1[0, 2, 2],
                         f'{imgeven1_centercropped[0]=}, {self.imgeven1[0]=}')

        # crop w/ same size: check identity
        imgeven1_randcropped, imgeven2_randcropped = np_crop_img_pair(self.imgeven1, self.imgeven2, 8, CropMethod.CENTER)
        self.assertTrue((imgeven1_randcropped == self.imgeven1).all(), 'Crop to same size is broken')


if __name__ == '__main__':
    unittest.main()