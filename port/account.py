from walless_utils import User


class Account:
    # Lower bound: 1kB. Default threshold: 100kB.
    SENSITIVITY_LOWER_BOUND = 2**10
    SENSITIVITY = 100 * 2**10

    def __init__(self, user):
        self.user: User = user
        # upload, download
        self.traffic = [0, 0]
        self.last_traffic = [0, 0]
        self.deleted = False
        self.threshold = self.SENSITIVITY

    def update_traffic(self, upload=None, download=None) -> bool:
        changed = False
        if upload is not None:
            if upload > self.traffic[0]:
                changed = True
            self.traffic[0] = max(upload, self.traffic[0])
        if download is not None:
            if download > self.traffic[1]:
                changed = True
            self.traffic[1] = max(download, self.traffic[1])
        return changed

    def reset(self):
        self.last_traffic = self.traffic.copy()
        self.threshold = self.SENSITIVITY

    def diff(self):
        return [self.traffic[i] - self.last_traffic[i] for i in range(2)]

    def need_report(self) -> bool:
        # If user traffic is above the threshold, report it.
        # Otherwise, lower the threshold by half. The minimum threshold is SENSITIVITY_LOWER_BOUND.
        if sum(self.diff()) >= self.threshold:
            return True
        self.threshold = max(self.SENSITIVITY_LOWER_BOUND, self.threshold // 2)
        return False

    def __repr__(self):
        return self.user.__repr__()

    def enable(self):
        self.deleted = False
        self.reset()

    def disable(self):
        self.deleted = True
        self.reset()
