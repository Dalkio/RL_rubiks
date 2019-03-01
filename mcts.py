import numpy as np
import math


class UCTNode():
    def __init__(self, game_state, parent=None, prior=0):
        self.game_state = game_state
        self.is_expanded = False
        self.parent = parent  # Optional[UCTNode]
        self.children = {}  # Dict[move, UCTNode]
        self.prior = prior  # float
        self.total_value = 0  # float
        self.number_visits = 0  # int

    def Q(self):  # returns float
        return self.total_value / (1 + self.number_visits)

    def U(self):  # returns float
        return (math.sqrt(self.parent.number_visits) * self.prior /
                (1 + self.number_visits))

    def best_child(self):
        return max(self.children.values(),
                   key=lambda node: node.Q() + node.U())

    def select_leaf(self):
        current = self
        while current.is_expanded:
            current.number_visits += 1
            current.total_value -= 1
            current = current.best_child()
        return current

    def expand(self, child_priors):
        self.is_expanded = True
        for move, prior in enumerate(child_priors):
            self.add_child(move, prior)

    def add_child(self, move, prior):
        self.children[move] = UCTNode(
            self.game_state.play(move), parent=self, prior=prior)

    def backup(self, value_estimate: float):
        current = self
        while current.parent is not None:
            current.total_value += value_estimate + 1
            current = current.parent


def UCT_search(game_state, num_reads):
    root = UCTNode(game_state)
    for _ in range(num_reads):
        leaf = root.select_leaf()
        child_priors, value_estimate = NeuralNet.evaluate(leaf.game_state)
        leaf.expand(child_priors)
        leaf.backup(value_estimate)
    return max(root.children.items(), key=lambda item: item[1].number_visits)


class NeuralNet():
    @classmethod
    def evaluate(self, game_state):
        return np.random.random([362]), np.random.random()


class GameState():
    def play(self, move):
        return GameState()