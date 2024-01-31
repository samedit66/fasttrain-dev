from collections import defaultdict
import warnings

import matplotlib.pyplot as plt
import numpy as np
import torch
from scipy.interpolate import PchipInterpolator

import json


def _add_ext(file_name, ext):
    if not ext.startswith("."):
        ext = f".{ext}"
    return file_name if file_name.endswith(ext) else f"{file_name}{ext}"


class History():
    
    def __init__(self, initial={}):
        self._stats_history = defaultdict(list, initial)

    @classmethod
    def from_json(cls, file_name):
        with open(_add_ext(file_name, "json"), "r") as input_file:
            stats_history = json.load(input_file)
        return History(stats_history)

    def to_json(self, file_name, indent_level=4):
        with(open(_add_ext(file_name, "json"), "r")) as output_file:
            json.dump(self.history, output_file, indent=indent_level)

    def update(self, stats):
        for k, v in stats.items():
            if not isinstance(v, float):
                v = float(v)
            self._stats_history[k].append(v)

    def __iter__(self):
        return iter(self._stats_history)

    def __getitem__(self, key):
        if not key in self._stats_history:
            raise KeyError(key)
        return self._stats_history[key]

    def items(self):
        return self._stats_history.items()

    @property
    def average(self):
        average_stats = {}
        for k, v in self._stats_history.items():
            average_stats[k] = sum(v) / len(v)
        return average_stats

    def plot(self,
             what: str,
             show: bool = True,
             with_val: bool = False,
             figsize: tuple[int, int] = (5, 5),
             smooth: bool = True):
        
        stats = {what: self._stats_history[what]}
        epochs = np.arange(1, len(stats[what])+1)
        ticks = labels = epochs
        if with_val:
            val_what = f"val_{what}"
            if val_what in self._stats_history:
                stats[val_what] = self._stats_history[val_what]
            else:
                warnings.warn('"with_val" is set to True, but no "val_" key was found in history')
        graph_name = what.capitalize()

        if smooth:
            epochs_ = np.linspace(epochs.min(), epochs.max(), 1000)
            for (name, stat) in stats.items():
                stats[name] = PchipInterpolator(epochs, stat)(epochs_)
            epochs = epochs_

        fig, ax = plt.subplots(figsize=figsize, layout="tight")
        for (name, stat) in stats.items():
            ax.plot(epochs, stat, label=name)
        ax.set_xlabel("Epoch")
        ax.set_xticks(ticks=ticks, labels=labels)
        ax.set_ylabel(graph_name)
        ax.set_title(f"{graph_name} over epochs")
        ax.legend()

        if show:
            plt.show()

        return (fig, ax)

    def visualize(self, *args, **kwargs):
        return self.plot(*args, **kwargs)