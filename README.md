nind-denoise
==============

A pytorch based image denoising tool for the removal of noise from real photographs. Implements the models developed in    
Benoit Brummer's [NIND Denoise](https://github.com/trougnouf/nind-denoise.git), and the 
[Darktable](https://github.com/darktable-org/darktable) workflow pioneered by [Huy Hoang](https://github.com/hqhoang).

This fork seeks make their work easier to experiment with, and to make it accessible to a wider audience. 
- Improved code portability via ```torch.accelerator```. 
  - In addition to supporting cpu-only and NVIDIA GPUs, this adds support for AMD & Intel GPU's, among others. Denoising (on mine) is about 6x
  faster than on cpu. (YMMV) 
- Documented installation process on Windows and linux 
  - Installs in a python virtual environment with [uv](https://github.com/astral-sh/uv)
  - Autodownload pretrained model weights from backblaze b2 -> simpler installation
  - To uninstall, just delete the directory.

- [...loading]

# Usage

To denoise an image, run:

```console
$ python3 src/denoise.py "/path/to/photo0123.RAW"
```

# Requirements

 - Darktable, and raw images processed with darktable to operate on, along with their .xmp files
 - gmic; on windows go [here](https://gmic.eu/download.html) and scroll down to get the "gmic-cli" version. extract to
 your home directory or be prepared to find the exectable and pass its location to denoise.py
 - [variant-enabled](https://astral.sh/blog/wheel-variants) uv
 - The correct gpu drivers for your system are installed along with OpenCL.
 - The oldest linux kernel confirmed working with intel's xpu acceleration is 6.14. So try and get one at least that 
new. 

## Darktable
 - If [this PR](https://github.com/darktable-org/darktable/pull/19189) is still open, you may need to limit yourself to 
version [5.0.1](https://github.com/darktable-org/darktable/releases/tag/release-5.0.1) in order to run rl-deblur.

### nVidia
 - Driver + CUDA

### AMD
 - (Untested as of yet) Possibly just a driver, possibly also ROCm-flavored openCL. Might not actually work. 

### Intel
 - Intel is slightly trickier, with version mismatches between system packages and venv packages causing memory 
alignment issues. Or so it seems. The working strategy is to install the minimum necessary and let uv/pip pull in the 
majority of dependencies inside the venv. Intel has a [guide](https://dgpu-docs.intel.com/driver/client/overview.html)
that details what you need for ubuntu that should give you an idea. Make sure not to overlook the bit that says _"However,
if you plan to use PyTorch, install `libze-dev` and `intel-ocloc` \[as well]"_ On arch linux start with 
 - `intel-compute-runtime`, `level-zero-loader` and `level-zero-headers`

Proper operation can be verified with:
 `clinfo | grep device` and `darktable-cltest`

# Installation:

Warning: this is a prototype developmental codebase. 
The following should be considered developer documentation (or at least for only those willing to experiment); it is not
yet a polished end user install guide.

To install, run the following commands. This should pull the right version of PyTorch for your gpu/cpu/xpu/whatever, but
if it doesn't, or you just want to avoid the possibility of iterating, continue reading below for how to modify to match
your hardware/environment. 

Good luck. Check out https://download.pytorch.org/whl/torch/ if you want to see a list of pytorch versions. 

### 1 - Clone this repo

```bash
git clone https://github.com/commreteris/nind-denoise.git
cd nind-denoise
```

### 2 - Create a virtual environment with `uv venv` and activate it.

- The fancy new varient-enabled version of uv makes it possible to _install_ the correct version of PyTorch for your GPU,
  automagically. We'll install that and use it to deploy the rest of the venv.
On **Windows** that would look something like this :

```powershell
PS> powershell -c { $env:INSTALLER_DOWNLOAD_URL = 'https://wheelnext.astral.sh'; irm https://astral.sh/uv/install.ps1 | iex }
PS> uv venv
PS> .venv/Scripts/activate
(nind-denoise) PS> Get-Command python

CommandType   Name          Version    Definition
-----------   ----          -------    ----------
Application   python.exe    3.1x.xx    C:\Users\<user>\...\nind-denoise\.venv/scripts\python.exe

```

From the output of the last command, make sure python.exe is defined inside the .venv directory. Don't proceed until it
is. 


On **Linux**, the following will work for most people. If you are a [fish](https://en.wikipedia.org/wiki/Fish_(Unix_shell)), or
otherwise out of water, go [here](https://docs.astral.sh/uv/pip/environments/#using-a-virtual-environment) for help. 

 ```bash
 [user@linux]$ curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_DOWNLOAD_URL=https://wheelnext.astral.sh sh
 [user@linux]$ uv venv
 [user@linux]$ source .venv/bin/activate
 [user@linux]$ which python
 /home/user/.../nind-denoise/.venv/bin/python
 [user@linux]$
 
```

From the output of the last command, make sure the python in your path is inside the .venv directory. Don't proceed 
until it is.

## 3 Install required python packages

Installing required packages into your `venv` should be the same for all operating systems, but it may have to be 
tweaked to match your hardware (_i.e.,_ GPU or lack thereof). This command _should_ work for all, but if it doesn't 
just scroll down and pick the right one yourself. 

```console
 $ uv pip install -r requirements.in --upgrade
```

### 4 Verify that PyTorch is picking up your GPU

If you want to make sure you have the expected acceleration provided by your hardware, you can open up a python console
and run some pytorch checks. To get to the python console, just type `python` in the same console as before. If you've
already closed it you'll have to navigate back to the nind-denoise directory and activate the venv again. For example, 
on a Windows machine with an nVidia GPU it might look like this:

```console
(nind-denoise) PS C:\Users\...\nind-denoise> python
Python 3.13.3 (main, Apr  8 2025, 04:04:49) [MSC v.1943 64 bit (AMD64)] on win32
Type "help", "copyright", "credits" or "license" for more information.
>>> import torch
>>> torch.accelerator.is_available()
True
>>> torch.cuda.is_available()
True
>>> torch.xpu.is_available()
False
>>> 
```

Go cite Benoit

```bibtex
@InProceedings{Brummer_2019_CVPR_Workshops,
author = {Brummer, Benoit and De Vleeschouwer, Christophe},
title = {Natural Image Noise Dataset},
booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR) Workshops},
month = {June},
year = {2019}
} 
```