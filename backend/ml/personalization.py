from sklearn.linear_model import LogisticRegression

from services.state import feedback_data


def train_model():
    if len(feedback_data) < 4:
        return None

    X = []
    y = []
    for feedback in feedback_data:
        X.append([feedback.energy, feedback.difficulty, feedback.duration])
        y.append(1 if feedback.completed else 0)

    if len(set(y)) < 2:
        return None

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)
    return model
