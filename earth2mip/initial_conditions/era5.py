# SPDX-FileCopyrightText: Copyright (c) 2023 NVIDIA CORPORATION & AFFILIATES.
# SPDX-FileCopyrightText: All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import dataclasses
import datetime
import json
import logging
import os
import warnings
from typing import Any

import s3fs
import xarray
import numpy as np

from earth2mip import config, filesystem, schema
from earth2mip.datasets import era5

__all__ = ["open_era5_xarray"]

logger = logging.getLogger(__name__)
# TODO move to earth2mip/datasets/era5?


@dataclasses.dataclass
class HDF5DataSource:
    root: str
    metadata: Any
    n_history: int = 0

    @classmethod
    def from_path(cls, root: str, **kwargs: Any) -> "HDF5DataSource":
        metadata_path = os.path.join(root, "data.json")
        metadata_path = filesystem.download_cached(metadata_path)
        with open(metadata_path) as mf:
            metadata = json.load(mf)
        return cls(root, metadata, **kwargs)

    @property
    def channel_names(self):
        return self.metadata["coords"]["channel"]

    @property
    def time_means(self):
        time_mean_path = os.path.join(self.root, "stats", "time_means.npy")
        time_mean_path = filesystem.download_cached(time_mean_path)
        return np.load(time_mean_path)

    def __getitem__(self, time: datetime.datetime):
        n_history = self.n_history
        path = _get_path(self.root, time)
        if path.startswith("s3://"):
            fs = s3fs.S3FileSystem(
                client_kwargs=dict(endpoint_url="https://pbss.s8k.io")
            )
            f = fs.open(path)
        else:
            f = None

        logger.debug(f"Opening {path} for {time}.")
        ds = era5.open_hdf5(path=path, f=f, metadata=self.metadata)
        subset = ds.sel(time=slice(None, time))
        # TODO remove n_history from this API?
        subset = subset[-n_history - 1 :]
        num_time = subset.sizes["time"]
        if num_time != n_history + 1:
            a = ds.time.min().values
            b = ds.time.max().values
            raise ValueError(
                f"{num_time} found. Expected: {n_history + 1} ."
                f"Time requested: {time}. Time range in data: {a} -- {b}."
            )
        return subset.load()


def _get_path(path: str, time) -> str:
    filename = time.strftime("%Y.h5")
    h5_files = filesystem.glob(os.path.join(path, "*/*.h5"))
    files = {os.path.basename(f): f for f in h5_files}
    return files[filename]


def open_era5_xarray(
    time: datetime.datetime, channel_set: schema.ChannelSet
) -> xarray.DataArray:
    warnings.warn(DeprecationWarning("This function will be removed"))
    root = config.get_data_root(channel_set)
    path = _get_path(root, time)
    logger.debug(f"Opening {path} for {time}.")

    if path.endswith(".h5"):
        if path.startswith("s3://"):
            fs = s3fs.S3FileSystem(
                client_kwargs=dict(endpoint_url="https://pbss.s8k.io")
            )
            f = fs.open(path)
        else:
            f = None
        if channel_set == schema.ChannelSet.var34:
            ds = era5.open_34_vars(path, f=f)
        else:
            metadata_path = os.path.join(config.ERA5_HDF5_73, "data.json")
            metadata_path = filesystem.download_cached(metadata_path)
            with open(metadata_path) as mf:
                metadata = json.load(mf)
            ds = era5.open_hdf5(path=path, f=f, metadata=metadata)

    elif path.endswith(".nc"):
        ds = xarray.open_dataset(path).fields

    return ds
