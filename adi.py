import logging
import sys
import os
import re
import random
import datetime
import numpy as np
from typing import Tuple
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import keras.backend as K
from keras import optimizers
from keras.layers import Input, Dense, Flatten
from keras.models import Model
from keras.models import model_from_json
from rubiks_cube import RubiksCube, RubiksAction


class ADI(object):
    def __init__(self, k: int = 25, l: int = 40000, initial_lr: float = 1e-5,
                 load_files: Tuple[str, str] = None, cube_dim: int = 3,
                 create_dataset: bool = True, save_dataset: bool = True, save_model: bool = True,
                 save_log: bool = True,
                 verbose: bool = True, shuffle: bool = True) -> None:
        """
        Autodidactic Iteration Algorithm for Rubik's Cube solving using reinforcement learning
        https://arxiv.org/pdf/1805.07470.pdf
        :param k: Number of scrambles from the solved state to generate a sequence of cubes
        :param l: Number of sequences generated
        :param initial_lr: Initial learning rate
        :param load_files: Tuple of dataset and weights filenames
        :param cube_dim: Dimension of cubes
        :param create_dataset: If true a full dataset if generated in memory using k and l parameters
        :param save_dataset: If true the created dataset is saved on disk
        :param save_model: If true the trained model is saved on disk
        :param save_log: Boolean for logging or not estimated accuracies
        :param verbose: Verbosity parameter
        :param shuffle: Dataset shuffle parameter
        """
        self.k = k
        self.l = l
        self.initial_lr = initial_lr
        self.load_files = load_files
        self.cube_dim = cube_dim
        self.create_dataset = create_dataset
        self.save_dataset = save_dataset
        self.save_model = save_model
        self.save_log = save_log
        self.verbose = verbose
        self.shuffle = shuffle

        self.X = None
        self.weights = None
        self.current_iteration = 0

        self.logger = self._create_logger()
        if self.load_files:
            self.cube_dim, self.k, self.l, self.X, self.weights = self._load_dataset()
        elif self.create_dataset:
            self.X, self.weights = self._generate_dataset(k=self.k, l=self.l, save_dataset=self.save_dataset)
        self.model = self._design_model()

    @staticmethod
    def _create_logger() -> logging.Logger:
        """
        Logger creator private method
        :return: logger
        """
        logger = logging.getLogger(__name__)
        formatter = logging.Formatter("%(asctime)s — %(funcName)s() — %(levelname)s — %(message)s")
        if logger.handlers:
            logger.addHandler(logger.handlers[0])
        else:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        return logger

    def _load_dataset(self) -> Tuple[int, int, int, np.ndarray, np.ndarray]:
        """
        Dataset loading private method
        :return: (dim, k, l, X, weights)
        """
        self.logger.info("Loading dataset...")
        assert len(self.load_files) == 2 and isinstance(self.load_files[0], str) \
            and isinstance(self.load_files[1], str), \
            "Bad format for load_files parameter"
        numbers_parsed = re.findall(r'\d+', self.load_files[0])
        assert len(numbers_parsed) == 4, \
            "Dataset file name incorrect"
        _, dim, k, l = [int(digit) for digit in numbers_parsed]
        self.logger.info("dim={0}, k={1}, l={2}".format(dim, k, l))
        X = np.load('data' + os.path.sep + self.load_files[0])
        weights = np.load('data' + os.path.sep + self.load_files[1])
        return dim, k, l, X, weights

    def _generate_dataset(self, k: int = 25, l: int = 40000, save_dataset: bool = True
                          ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Dataset generation private method
        Some parameters are passed here to make possible online dataset generation in the train method
        :param k: Number of scrambles from the solved state to generate a sequence of cubes
        :param l: Number of sequences generated
        :param save_dataset: Boolean for saving or not the created dataset
        :return: (X, weights)
        """
        self.logger.info("Generating dataset...")
        X, weights = [], []
        for iteration in range(l):
            rubiks_cube = RubiksCube(dim=self.cube_dim, shuffle=False, verbose=False)
            inverse_previous_action_idx = None
            for shuffle in range(k):
                action_idx = random.choice(
                    [idx for idx in range(len(rubiks_cube.actions)) if idx != inverse_previous_action_idx]
                )
                action = RubiksAction(rubiks_cube.actions[action_idx])
                rubiks_cube.step(action)
                inverse_previous_action_idx = rubiks_cube.index_actions[str(action.get_inverse_action())]
                weight = 1 / (shuffle + 1)
                X.append(rubiks_cube.state_one_hot)
                weights.append(weight)
            if self.verbose and iteration % (l / 10) == 0:
                self.logger.info("{0:.2f}%".format((iteration / l) * 100))
        X, weights = np.asarray(X), np.asarray(weights)
        if self.shuffle:
            random_indexes = np.random.permutation(range(l * k))
            X, weights = X[random_indexes], weights[random_indexes]
        os.makedirs('data', exist_ok=True)
        if save_dataset:
            samples_file = "data/scrambled_cubes_{0}x{0}_k{1}_l{2}.npy".format(self.cube_dim, k, l)
            weights_file = "data/weights_{0}x{0}_k{1}_l{2}.npy".format(self.cube_dim, k, l)
            np.save(samples_file, X)
            np.save(weights_file, weights)
        return X, weights

    def _design_model(self) -> Model:
        rubiks_cube = RubiksCube(dim=self.cube_dim)

        inputs = Input(shape=rubiks_cube.state_one_hot.shape, name='input')
        x = Flatten()(inputs)
        x = Dense(4096, activation='elu')(x)
        x = Dense(2048, activation='elu')(x)
        pre_v = Dense(512, activation='elu')(x)
        pre_p = Dense(512, activation='elu')(x)
        v = Dense(1, activation='linear', name='value_output')(pre_v)
        p = Dense(12, activation='softmax', name='policy_output')(pre_p)

        losses = {
            'value_output': 'mean_squared_error',
            'policy_output': 'categorical_crossentropy'
        }
        opt = optimizers.Adam(lr=self.initial_lr)

        model = Model(inputs=inputs, outputs=[v, p])
        model.compile(optimizer=opt, loss=losses)
        return model

    def save_trained_model(self, filename: str) -> None:
        """
        Save the trained model in local
        :param filename: Root filename for the config stored as json, and the model itself stored as h5
        :return: None
        """
        model_name_json, model_name_h5 = filename + '.json', filename + '.h5'
        model_json = self.model.to_json()
        with open(model_name_json, "w") as json_file:
            json_file.write(model_json)
        self.model.save_weights(model_name_h5)
        
    def load_trained_model(self, filename: str, current_iteration: int) -> None:
        """
        Save the trained model in local
        :param filename: Root filename for the config stored as json, and the model itself stored as h5
        :param current_iteration: Current iteration on the model
        :return: None
        """
        model_name_json, model_name_h5 = 'data/' + filename + '.json', 'data/' + filename + '.h5'
        with open(model_name_json, 'r') as json_file:
            loaded_model = model_from_json(json_file.read())
        loaded_model.load_weights(model_name_h5)
        losses = {
            'value_output': 'mean_squared_error',
            'policy_output': 'categorical_crossentropy'
        }
        loaded_model.compile(optimizer='rmsprop', loss=losses)
        self.model = loaded_model
        self.current_iteration = current_iteration

    def train(self, generate_online_dataset: bool = False,
              k: int = None, l: int = None,
              lr_decay: bool = True, lr_decay_gamma: float = 0.95, lr_decay_freq = 1000,
              batch_size: int = 1000, batches_number: int = 5, epochs_per_batch: int = 1,
              save_frequency: int = 10, log_frequency: int = 5) -> None:
        """
        :param generate_online_dataset: If true, generate its own dataset for each batch
        :param k: k parameter per batch, only used if generate_online_dataset is True
        :param l: l parameter per batch, only used if generate_online_dataset is True
        :param lr_decay: Enable learning rate decay between batches
        :param lr_decay_gamma: Learning rate gamma, only used if lr_decay is True
        :param lr_decay_freq: Learning rate updates interval, only used if lr_decay is True
        :param batch_size: Number of cubes for a batch for one pass, only used if generate_online_dataset is False
        :param batches_number: Number of total epochs
        :param epochs_per_batch: Number of epochs for one batch
        :param save_frequency: Number of batches between each saving
        :param log_frequency: Number of batches between each logging
        :return: None
        """
        self.logger.info("Training model...")
        rubiks_cube = RubiksCube(dim=self.cube_dim)
        for _ in range(batches_number):
            self.current_iteration += 1
            self.logger.info("Batch number: {0}".format(self.current_iteration))
            if generate_online_dataset:
                assert k is not None and l is not None
                X_batch, weights_batch = self._generate_dataset(k=k, l=l, save_dataset=False)
                batch_size = len(X_batch)
            else:
                assert self.X is not None and self.weights is not None
                k, l = self.k, self.l
                batch_indexes = np.random.choice(range(len(self.X)), size=batch_size, replace=False)
                X_batch, weights_batch = self.X[batch_indexes], self.weights[batch_indexes]
            rewards, states = [], []
            for X_i in X_batch:
                rewards_i, states_i = [], []
                for action in rubiks_cube.actions:
                    states_a, reward_a, _, _ = RubiksCube(dim=self.cube_dim, cube=X_i).step(RubiksAction(action))
                    rewards_i.append(reward_a)
                    states_i.append(RubiksCube.to_one_hot_cube(states_a))
                rewards.append(np.asarray(rewards_i))
                states.append(np.asarray(states_i))

            rewards, states = np.asarray(rewards), np.asarray(states)
            states = states.reshape(-1, *states.shape[2:])

            (values, _) = self.model.predict(states)
            values = values.reshape((batch_size, len(rubiks_cube.actions)))

            Y_v = np.max(rewards + values, axis=1)
            Y_p = np.eye(len(rubiks_cube.actions))[np.argmax(rewards + values, axis=1)]

            if lr_decay:
                if self.current_iteration%lr_decay_freq == 0:
                    current_lr = K.eval(self.model.optimizer.lr)
                    new_lr = current_lr * lr_decay_gamma
                    K.set_value(self.model.optimizer.lr, new_lr)
                    self.logger.info("Changed LR from {0:.3E} to {1:.3E}".format(current_lr, new_lr))

            history = self.model.fit(
                {'input': X_batch},
                {'policy_output': Y_p, 'value_output': Y_v},
                sample_weight={'policy_output': weights_batch, 'value_output': weights_batch},
                epochs=epochs_per_batch
            )
            loss = history.history['loss'][-1]
            if self.save_log:
                if self.current_iteration%log_frequency == 0:
                    os.makedirs('log', exist_ok=True)
                    now = datetime.datetime.today().strftime('%Y-%m-%d')
                    filename = 'log/{0}.log'.format(now)
                    precision_iter = 500
                    acc = np.mean([
                        self.estimate_naive_accuracy(depth=i, iterations=precision_iter) for i in range(1, k+1)
                    ])
                    s_log = '{0} - epochs{1}_bs{2}_dim{3}x{3}_k{4}_l{5}_lr{6:.1E}_iter{7}: loss={8:.5f}, acc={9:.5f}\n'
                    with open(filename, 'a') as f:
                        f.write(
                            s_log.format(
                                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                epochs_per_batch, batch_size,
                                self.cube_dim, k, l, K.eval(self.model.optimizer.lr), self.current_iteration,
                                loss, acc
                            )
                        )
            if self.save_model:
                if self.current_iteration%save_frequency == 0:
                    filename = "data/model_{0}x{0}_k{1}_l{2}_iter{3}".format(
                        self.cube_dim, k, l, self.current_iteration
                    )
                    self.save_trained_model(filename)

    def estimate_naive_accuracy(self, depth: int, iterations: int) -> float:
        """
        :param depth: Maximum scramble depth in the accuracy approximation
        :param iterations: Number of iterations, a higher value leads to a better accuracy approximation
        :return: Approximated accuracy
        """
        score = 0
        for iteration in range(iterations):
            rubiks = RubiksCube(dim=self.cube_dim, shuffle=False)
            inverse_previous_action_idx = None
            for depth_i in range(depth):
                action_idx = random.choice(
                    [idx for idx in range(len(rubiks.actions)) if idx != inverse_previous_action_idx]
                )
                action = RubiksAction(rubiks.actions[action_idx])
                rubiks.step(action)
                inverse_previous_action_idx = rubiks.index_actions[str(action.get_inverse_action())]
            (_, p) = self.model.predict(np.expand_dims(rubiks.state_one_hot, axis=0))
            prediction = np.argmax(p)
            score += prediction == inverse_previous_action_idx
        return score/iterations
