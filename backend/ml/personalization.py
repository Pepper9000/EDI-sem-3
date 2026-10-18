from sklearn.linear_model import LogisticRegression

from services import state as state_module


def train_model():
    if len(state_module.feedback_data) < 4:
        return None

    X = []
    y = []
    for feedback in state_module.feedback_data:
        X.append([feedback.energy, feedback.difficulty, feedback.duration])
        y.append(1 if feedback.completed else 0)

    if len(set(y)) < 2:
        return None

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)
    return model
