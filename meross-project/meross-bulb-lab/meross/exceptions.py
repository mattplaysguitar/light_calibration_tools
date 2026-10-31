class MerossError(RuntimeError):
    pass


class MerossLocalError(MerossError):
    pass


class MerossRemoteError(MerossError):
    pass
