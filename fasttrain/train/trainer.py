from abc import ABC, abstractmethod
from collections.abc import Sequence, Mapping
from typing import Optional, Union

import torch
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

from ..callbacks import (
    Callback,
    Tqdm    
    )
from .history import History
from .device import (
    load_data_on_device,
    find_suitable_device,
    )


_OptimizerAndScheduler = Union[torch.optim.Optimizer, torch.optim.lr_scheduler.LRScheduler]


class Trainer(ABC):
    '''
    Base class for all user defined trainers. Usually, to make up a trainer,
    one should subclass `Trainer` and define `predict`, `compute_loss` and `eval_metrics`.
    Although, you don't have to always define `predict` (see its docs).
    '''

    def __init__(self,
                 model: torch.nn.Module,
                 optimizer: torch.optim.Optimizer,
                 ) -> None:
        '''
        :param model: Model to train.
        :param optimizer: Optimizer for the model.
        '''
        self._model = model
        self._opt = optimizer
        self._device = None
        self._is_training = False
        self._callbacks = []
        self._last_on_epoch_end_logs = {}
        self._verbose = True
        self._in_notebook = None

    def predict(self, input_batch):
        '''
        This function is called every time when the model predictions are needed.
        By default it expects a batch which should be a tuple or a list with 2 elements -
        x-batch and y-batch. If your training data differs, you need to define a custom
        predict function.
        :param input_batch: Batch that the DataLoader yields.
        :return: Model output batch.
        '''
        if isinstance(input_batch, Sequence):
            (x_batch, _) = input_batch
            return self.model(x_batch)
        
        raise TypeError('Predefined predict failed, perhaps you need to define '
                        'your custom predict function'
                        )

    @abstractmethod
    def compute_loss(self, input_batch, output_batch) -> torch.Tensor:
        '''
        This function is called every time when the loss value is needed.
        You need to define how the loss value is computed.
        This method must return a `torch.Tensor`.

        :param input_batch: Batch that the DataLoader yields.
        :param output_batch: Model output batch.
        :return: Loss value.
        '''

    def eval_metrics(self, input_batch, output_batch) -> Optional[Mapping]:
        '''
        Evaluates metrics. Called everytime when model predictions are made.
        If defined, the returned metrics are stored in a `History`.
        Metrics must be a dict or a mapping.

        :param input_batch: Batch that the DataLoader yields.
        :param output_batch: Model output batch.
        :return: Metrics.
        '''
        return None

    @property
    def model(self) -> torch.nn.Module:
        '''
        Returns the training model.

        :return: Training model.
        '''
        return self._model

    @property
    def is_training(self) -> bool:
        '''
        Returns a bool value whether the model is training now.

        :return: `True` if the model is training, `False` otherwise. 
        '''
        return self._is_training

    #@abstractmethod
    def load_dataset(self) -> None:
        '''
        Loads the dataset.
        Define here download instructions, splits, preprocessing and other such things.
        This method does not return anything: store the dataset as `Trainer` attributes.
        '''

    #@abstractmethod
    def train_data_loader(self) -> torch.utils.data.DataLoader:
        '''
        Makes up a training `DataLoader`.
        '''

    def val_data_loader(self) -> Optional[torch.utils.data.DataLoader]:
        '''
        Makes up a validation `DataLoader`. If defined, used to obtain the validation `DataLoader`.
        '''
        return None
    
    def test_data_loader(self) -> Optional[torch.utils.data.DataLoader]:
        '''
        Makes up a test `DataLoader`. If defined, used to obtain the test `DataLoader`.
        '''
        return None
    
    #@abstractmethod
    def make_optimizer(self) -> torch.optim.Optimizer | _OptimizerAndScheduler:
        '''
        Makes up an optimizer with ot without a learning rate scheduler.
        '''

    def _stop_training(self) -> None:
        '''
        Stops the training. Must be called only inside a `Callback` class.
        '''
        self._is_training = False

    def _on_train_begin(self):
        for cb in self._callbacks:
            cb.on_train_begin()

    def _on_train_end(self):
        for cb in self._callbacks:
            cb.on_train_end(self._last_on_epoch_end_logs)

    def _on_epoch_begin(self, epoch_num):
        for cb in self._callbacks:
            cb.on_epoch_begin(epoch_num)

    def _on_epoch_end(self, epoch_num, logs):
        self._last_on_epoch_end_logs = logs
        for cb in self._callbacks:
            cb.on_epoch_end(epoch_num, logs)

    def _on_train_batch_begin(self, batch_num):
        for cb in self._callbacks:
            cb.on_train_batch_begin(batch_num)

    def _on_train_batch_end(self, batch_num, logs):
        for cb in self._callbacks:
            cb.on_train_batch_end(batch_num, logs)

    def _on_validation_begin(self):
        for cb in self._callbacks:
            cb.on_validation_begin()

    def _on_validation_end(self, logs):
        for cb in self._callbacks:
            cb.on_validation_end(logs)

    def _on_validation_batch_begin(self, batch_num):
        for cb in self._callbacks:
            cb.on_validation_batch_begin(batch_num)

    def _on_validation_batch_end(self, batch_num, logs):
        for cb in self._callbacks:
            cb.on_validation_batch_end(batch_num, logs)

    def _log(self, message: str) -> None:
        '''
        Logs a message to stdout. Should be used to inform user about model training because
        ordinary `print` may break up the progress bar. Use it only inside a custom `Callback`.
        
        :param message: Message to log.
        '''
        if self.is_training:
            tqdm.write(message)
        else:
            print(message)

    def _is_in_notebook(self) -> bool:
        try:
            shell = get_ipython().__class__.__name__
            if shell == 'ZMQInteractiveShell':
                return True   # Jupyter notebook or qtconsole
            elif shell == 'TerminalInteractiveShell':
                return False  # Terminal running IPython
            else:
                return False  # Other type (?)
        except NameError:
            return False      # Probably standard Python interpreter

    def _is_in_colab(self) -> bool:
        try:
            import google.colab
            return True
        except:
            return False

    def _setup_callbacks(self,
                         user_callbacks,
                         training_args: dict,
                         ) -> None:
        if user_callbacks is None:
            user_callbacks = []

        if self._verbose:
            if self._in_notebook is None:
                self._in_notebook = self._is_in_notebook() or self._is_in_colab()

            self._log(f'Running as a {"notebook" if self._in_notebook else "script"}')
            progress_bar = Tqdm(in_notebook=self._in_notebook)
            progress_bar.model = self.model
            progress_bar.trainer = self
            progress_bar.training_args = training_args
            self._callbacks.append(progress_bar)
        
        for user_callback in user_callbacks:
            if self._verbose and isinstance(user_callbacks, Tqdm):
                continue

            user_callback.model = self.model
            user_callback.trainer = self
            user_callback.training_args = training_args
            self._callbacks.append(user_callback)

    def _get_data_loader(self,
                         data: Dataset | DataLoader,
                         batch_size: int,
                         shuffle: bool) -> DataLoader:
        if (data is None) or isinstance(data, DataLoader):
            return data
        return DataLoader(data, batch_size=batch_size, shuffle=shuffle)

    def _compute_loss(self,
                      input_batch,
                      training: bool
                      ):
        output_batch = self.predict(input_batch)
        loss = self.compute_loss(input_batch, output_batch)

        if training:
            loss.backward()
            self._opt.step()
            self._opt.zero_grad()

        return (output_batch, loss.item())
    
    def _train(self, dl: DataLoader) -> Mapping:
        self.model.train()

        history = History()
        data_gen = load_data_on_device(dl, self._device)
        for (batch_num, input_batch) in enumerate(data_gen):
            self._on_train_batch_begin(batch_num)
            if not self.is_training:
                break

            output_batch, loss_value = self._compute_loss(input_batch, training=True)
            metrics = self.eval_metrics(input_batch, output_batch) or {}
            metrics["loss"] = loss_value
            history.update(metrics)

            self._on_train_batch_end(batch_num, history.average)
            if not self.is_training:
                break
        
        return history.average
    
    @torch.no_grad()
    def _validate(self, dl: DataLoader) -> Mapping:
        self.model.eval()

        history = History()
        data_gen = load_data_on_device(dl, self._device)
        for (batch_num, input_batch) in enumerate(data_gen):
            self._on_validation_batch_begin(batch_num)
            if not self.is_training:
                break

            output_batch, loss_value = self._compute_loss(input_batch, training=False)
            metrics = self.eval_metrics(input_batch, output_batch) or {}
            metrics = {f'val_{k}': v for (k, v) in metrics.items()}
            metrics['val_loss'] = loss_value
            history.update(metrics)
            
            self._on_validation_batch_end(batch_num, history.average)
            if not self.is_training:
                break

        return history.average

    def _training_loop(self,
                       train_dl: DataLoader,
                       val_dl: DataLoader,
                       num_epochs: int,
                       ) -> History:
        history = History()

        self._is_training = True
        self._on_train_begin()
        current_epoch_num = 1

        while self.is_training and current_epoch_num <= num_epochs:
            self._on_epoch_begin(current_epoch_num)
            if not self.is_training:
                break

            metrics = self._train(train_dl)
            if val_dl is not None:
                metrics |= self._validate(val_dl)
            history.update(metrics)

            self._on_epoch_end(current_epoch_num, metrics)
            if not self.is_training:
                break 

            current_epoch_num += 1

        self._stop_training()
        self._on_train_end()

        return history

    def train(self,
              train_data: Dataset | DataLoader,
              num_epochs: int,
              verbose: bool = True,
              device: str | torch.device = 'auto',
              force_device: bool = True,
              val_data: Dataset | DataLoader | None = None,
              batch_size: int = 16,
              shuffle: bool = True,
              callbacks: Sequence[Callback] | None = None,
              in_notebook: bool | None = None,
              ) -> History:
        '''
        Trains the model for a fixed number of epochs.

        :param train_data: A Dataset or DataLoader object. If it's a DataLoader,
        `batch_size` and `shuffle` are ignored. Otherwise, `train` makes up a DataLoader
            from the given Dataset object.
        :param num_epochs: Integer. Number of epochs to train the model.
        :param verbose: Verbosity mode. Default to `True`. If `False`, no progress bar
            appears and no messages are printed.
        :param device: `"auto"`, `"cpu"`, `"cuda"`. Default to `"auto"`. If `"auto"`, tries
            to automatically detect suitable device for training, preferrably, cuda. 
        :param force_device: Boolean. If `True` and `device` is not available, raises `RuntimeError`. Default to `True`.
            Used if `device` is not `"auto"`.
        :param val_data: Data on which to evaluate the loss and any model metrics at the end of each epoch.
            The model will not be trained on this data. Can be either a `Dataset` or `DataLoader` object. If it is a DataLoader,
            `batch_size` and `shuffle` are ignored. Otherwise, `train` makes up a validation DataLoader
            from the given Dataset object.
        :param batch_size: Integer. Default to 16. Used when `train_data` or `val_data` are not DataLoaders.
        :param shuffle: Boolean, whether to shuffle the training data before each epoch. Default to `True`.
            Used when `train_data` or `val_data` are not `DataLoaders`.
        :param callbacks: Callbacks to interact with the model and metrics during various stages of training.
            The use of the progress bar callback is controlled by `verbose`, one don't need to add it explicity.
        :param in_notebook: Used to correctly display the progress bar. If `None`, tries to automatically detect
            whether running in a notebook or not. If `True`, forces to show a progress bar as it looks in a notebook
            (leads to a strange-looking progress bar when not in a notebook).
        :return: History object. The history of training which includes validation metrics if `val_data` present.
        '''
        available_device = find_suitable_device(desired_device=device)
        if device != "auto" and str(available_device) != str(device):
            if force_device:
                raise RuntimeError(f'Device {device} not available')
            self._log(f'Device {device} not available, using {available_device}')
        else:
            self._log(f'Using {available_device}')

        self._device = available_device
        self._model = self._model.to(self._device)

        train_dl = self._get_data_loader(train_data, batch_size, shuffle)
        val_dl = self._get_data_loader(val_data, batch_size, shuffle)

        self._verbose = verbose
        self._in_notebook = in_notebook
        training_args = {
            'num_epochs': num_epochs,
            # TODO: Разобраться с IterableDataset при мультипроцессной загрузке данных
            'num_batches': len(train_dl),
            }
        self._setup_callbacks(callbacks, training_args)

        history = self._training_loop(train_dl, val_dl, num_epochs)
        return history
