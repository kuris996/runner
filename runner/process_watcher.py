from runner.ticker import Ticker

class ProcessWatcher(Ticker):
    def __init__(self, process, finished = None):
        super().__init__(1.0, self.__tick)
        self.__process = process
        self.__finished = finished

    def exitcode(self):
        return self.__process.exitcode

    def start_watch(self):
        self.__process.start()
        self.start()

    def __tick(self):
        if self.__process.exitcode == None:
            return
        self.stop()
        if self.__finished == None:
            return
        self.__finished(self)
