from .reductions import get_numpy_reduction
from tornasole.core.modes import ModeKeys
from tornasole.exceptions import *

from tornasole.core.index_reader import IndexReader

from enum import Enum
import bisect


class StepState(Enum):
    UNAVAILABLE = 0
    AVAILABLE = 1
    NOT_YET_AVAILABLE = 2


class ModeSteps:
    def __init__(self, mode, cache=False):
        self.mode = mode
        self.cache = cache
        self._steps = {}

    def steps(self):
        ts = list(self._steps.keys())
        ts.sort(key=int)
        return ts

    def has_step(self, step_num):
        return step_num in self._steps

    def set_step_value(self, step_num, value):
        if step_num not in self._steps:
            self._steps[step_num] = Step(step_num, value, self.cache)
        else:
            s = self._steps[step_num]
            s.value = value

    def set_step_location(self, step_num, location):
        if step_num not in self._steps:
            self._steps[step_num] = Step(step_num, location=location, cache=self.cache)
        s = self._steps[step_num]
        s.location = location

    def set_step_reduction_value(self, step_num, red_name, abs, red_value):
        if step_num not in self._steps:
            s = Step(step_num, cache=self.cache)
            self._steps[step_num] = s
        else:
            s = self._steps[step_num]
        s.set_reduction_value(red_name, abs, red_value)

    def set_step_reduction_location(self, step_num, red_name, abs, red_location):
        if step_num not in self._steps:
            s = Step(step_num, cache=self.cache)
            self._steps[step_num] = s
        else:
            s = self._steps[step_num]
        s.set_reduction_location(red_name, abs, red_location)

    def step(self, step_num):
        return self._steps[step_num]


class Step:
    def __init__(self, step_num, value=None, location=None, cache=False):
        self.step_num = step_num
        self._value = value
        self.location = location
        self.cache = cache

        # mapping from (red_name, abs) to value
        self._reduction_values = {}
        self._reduction_locations = {}

    @property
    def value(self):
        if self._value is None:
            if self.location is None:
                return None
            else:
                value = IndexReader.fetch_tensor_value(self.location)
                if self.cache:
                    self._value = value
                return value
        return self._value

    @value.setter
    def value(self, value):
        self._value = value

    @value.deleter
    def value(self):
        del self._value

    def reduction_values(self):
        reduction_values = {}
        if not self._reduction_values:
            for reduction in self._reduction_locations:
                red_name = reduction[0]
                abs = reduction[1]
                reduction_value = IndexReader.fetch_tensor_value(self._reduction_locations[(red_name, abs)])
                if self.cache:
                    self.set_reduction_value(red_name,
                                             abs,
                                             reduction_value
                                             )
                reduction_values[(red_name, abs)] = reduction_value
            return reduction_values
        return self._reduction_values

    def reduction_value(self, red_name, abs):
        reduction_values = self._reduction_values
        if not reduction_values:
            reduction_values = self.reduction_values()
        if (red_name, abs) in reduction_values:
            return reduction_values[(red_name, abs)]

    def reduction_locations(self):
        return self._reduction_locations

    def reduction_location(self, red_name, abs):
        if (red_name, abs) in self._reduction_locations:
            return self._reduction_locations[(red_name, abs)]

    def set_reduction_value(self, red_name, abs, red_value):
        self._reduction_values[(red_name, abs)] = red_value

    def set_reduction_location(self, red_name, abs, red_location):
        self._reduction_locations[(red_name, abs)] = red_location


# refreshing is always responsibility of tensor class at the highest level API function,
# not ModeSteps/Steps
class Tensor:
    def __init__(self, name, trial, cache):
        self._mode_steps = {}
        self.name = name
        self.trial = trial
        self.cache = cache

    def steps(self, mode=ModeKeys.GLOBAL):
        self.trial.maybe_refresh(self.name)
        if mode == ModeKeys.GLOBAL:
            return self._global_steps()
        elif mode in self._mode_steps:
            return self._mode_steps[mode].steps()
        else:
            return None

    def _global_steps(self):
        gs = []
        for mode in self._mode_steps:
            ms = self._mode_steps[mode].steps()
            for s in ms:
                gs.append(self.trial.global_step(mode, s))
        gs.sort(key=int)
        return gs

    def _has_step(self, step_num, mode=ModeKeys.GLOBAL):
        if self._has_step_currently(step_num, mode):
            return True
        else:
            self.trial.maybe_refresh(self.name)
            if self._has_step_currently(step_num, mode):
                return True
        return False

    def _has_step_currently(self, step_num, mode):
        if mode == ModeKeys.GLOBAL:
            return self._has_global_step_currently(step_num)
        else:
            return self._has_mode_step_currently(step_num, mode)

    def _has_mode_step_currently(self, step_num, mode):
        if mode in self._mode_steps:
            if self._mode_steps[mode].has_step(step_num):
                return True
        return False

    def _has_global_step_currently(self, step_num):
        # first check if in global mode,
        if ModeKeys.GLOBAL in self._mode_steps:
            if self._mode_steps[ModeKeys.GLOBAL].has_step(step_num):
                return True
        else:
            # else convert to mode_step and check
            mode, mode_step_num = self.trial.mode_modestep(step_num)
            if mode in self._mode_steps and \
                    self._mode_steps[mode].has_step(mode_step_num):
                return True
        return False

    def _get_step_currently(self, step_num, mode):
        if mode == ModeKeys.GLOBAL and ModeKeys.GLOBAL in self._mode_steps \
                and self._mode_steps[ModeKeys.GLOBAL].has_step(step_num):
            # step was saved as GLOBAL step
            return self._mode_steps[mode].step(step_num)
        else:
            if mode == ModeKeys.GLOBAL:
                # else convert to mode_step and check
                mode, step_num = self.trial.mode_modestep(step_num)
            if self._has_mode_step_currently(step_num, mode):
                return self._mode_steps[mode].step(step_num)
        return None

    def step(self, step_num, mode=ModeKeys.GLOBAL):
        s = self._get_step_currently(step_num, mode)
        if s is not None:
            return s
        else:
            self.trial.maybe_refresh(self.name)
            ss = self.trial.has_passed_step(step_num, mode)
            if ss == StepState.AVAILABLE:
                s = self._get_step_currently(step_num, mode)
                if s is not None:
                    return s
                raise TensorUnavailableForStep(self.name, step_num, mode)
            elif ss == StepState.UNAVAILABLE:
                raise StepUnavailable(step_num, mode)
            elif ss == StepState.NOT_YET_AVAILABLE:
                if self.trial.loaded_all_steps is True:
                    last_step = -1
                    avail_steps = self.trial.available_steps(mode=mode)
                    if len(avail_steps) > 0:
                        last_step = avail_steps[-1]
                    raise NoMoreData(
                        "Looking for step:{} for mode {} and reached end of training. Max step available is {}".format(
                            step_num, mode, last_step))
                raise StepNotYetAvailable(step_num, mode)
        assert False, 'Should not happen'

    def value(self, step_num, mode=ModeKeys.GLOBAL):
        # step refreshes
        s = self.step(step_num=step_num, mode=mode)
        if s.value is not None:
            return s.value
        elif s.location is not None:
            value = IndexReader.fetch_tensor_value(s.location)
            if self.cache:
                s.value = value
            return value
        else:
            has_reductions = len(s.reduction_values()) > 0
            raise TensorUnavailableForStep(self.name, step_num, mode, has_reductions)

    def reduction_values(self, step_num, mode=ModeKeys.GLOBAL):
        s = self.step(step_num=step_num, mode=mode)
        if s is not None:
            return s.reduction_values()
        else:
            assert False, 'Should not happen'

    def reduction_value(self, step_num, reduction_name, mode=ModeKeys.GLOBAL, abs=False):
        """
        Returns the value of the reduction requested.
        If the tensor was saved as a reduction, then just fetches that.
        Else, tries to compute the reduction and returns. If the tensor value is not
        available, returns None as reduction

        :param step_num: step number
        :param mode: mode of job (train, eval, predict, etc).
                            If this is None, assumes step number is global
        :param reduction_name: name of reduction
        :param abs: boolean which represents whether reduction should
                    be applied on absolute value of the tensor or not
        :return: reduction value requested as a float
        """
        s = self.step(step_num=step_num, mode=mode)
        rv = s.reduction_value(reduction_name, abs)
        rl = s.reduction_location(reduction_name, abs)
        if rv is not None:
            return rv
        elif rl is not None:
            return IndexReader.fetch_tensor_value(rl)
        else:
            if s.value is None:
                step_value = IndexReader.fetch_tensor_value(s.location)
                if self.cache:
                    s.value = step_value  # save value if cache is set to True
            else:
                step_value = s.value
            return get_numpy_reduction(reduction_name, step_value, abs)

        assert False, 'Should not happen'

    def _create_mode_step(self, mode, mode_step):
        mode_step = int(mode_step)
        if mode_step < 0:
            raise ValueError('mode step number {} for tensor {} '
                             'can not be less than 0'.format(mode_step, self.name))
        if mode not in self._mode_steps:
            self._mode_steps[mode] = ModeSteps(mode, cache=self.cache)

    def add_step(self, mode, mode_step, value):
        self._create_mode_step(mode, mode_step)
        self._mode_steps[mode].set_step_value(mode_step, value)

    def add_reduction_step(self, mode, mode_step, red_name, abs, red_value):
        self._create_mode_step(mode, mode_step)
        self._mode_steps[mode].set_step_reduction_value(mode_step,
                                                        red_name, abs, red_value)

    def add_step_lazy(self, mode, mode_step, location):
        self._create_mode_step(mode, mode_step)
        self._mode_steps[mode].set_step_location(mode_step, location)

    def add_reduction_step_lazy(self, mode, mode_step, red_name, abs, red_location):
        self._create_mode_step(mode, mode_step)
        self._mode_steps[mode].set_step_reduction_location(mode_step,
                                                        red_name, abs, red_location)

    def prev_steps(self, step, n=None, mode=ModeKeys.GLOBAL):
        """
        returns n prev steps from step representing step number
        of given mode including step
        :param step: int
            step number
        :param n: int
            number of previous steps to return
            if None returns all previous steps before step
        :param mode: value of the enum tornasole.modes
            modes.GLOBAL, modes.TRAIN, modes.EVAL, modes.PREDICT
        :return: a list of step numbers
        """
        steps = self.steps(mode=mode)
        i = bisect.bisect_right(steps, step)
        prev_steps = steps[:i]
        if n:
            return prev_steps[-n:]
        else:
            return prev_steps
