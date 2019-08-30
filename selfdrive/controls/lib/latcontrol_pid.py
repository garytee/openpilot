from selfdrive.controls.lib.pid import PIController
from selfdrive.controls.lib.drive_helpers import get_steer_max
from cereal import car
from cereal import log
from selfdrive.virtualZSS import virtualZSS_wrapper
#from selfdrive.kegman_conf import kegman_conf


class LatControlPID(object):
  def __init__(self, CP):
    self.pid = PIController((CP.lateralTuning.pid.kpBP, CP.lateralTuning.pid.kpV),
                            (CP.lateralTuning.pid.kiBP, CP.lateralTuning.pid.kiV),
                            k_f=CP.lateralTuning.pid.kf, pos_limit=1.0)
    self.angle_steers_des = 0.

    # virtualZSS
    self.model_wrapper = virtualZSS_wrapper.get_wrapper()
    self.model_wrapper.init_model()
    self.output_steer = 0
    self.past_data = []
    self.seq_len = 20

  def reset(self):
    self.pid.reset()

  def update(self, active, v_ego, angle_steers, angle_steers_rate, eps_torque, steer_override, CP, VM, path_plan, driver_torque):
    # virtualZSS
    self.past_data.append([angle_steers, self.output_steer])
    while len(self.past_data) > self.seq_len:
      del self.past_data[0]

    if len(self.past_data) == self.seq_len:
      angle_steers = float(self.model_wrapper.run_model_time_series([i for x in self.past_data for i in x]))
    else:  # if we haven't gathered past 20 timesteps yet, use regular model
      angle_steers = float(self.model_wrapper.run_model(angle_steers, self.output_steer))

    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steerAngle = float(angle_steers)
    pid_log.steerRate = float(angle_steers_rate)

    if v_ego < 0.3 or not active:
      output_steer = 0.0
      pid_log.active = False
      self.pid.reset()
    else:
      self.angle_steers_des = path_plan.angleSteers  # get from MPC/PathPlanner

      steers_max = get_steer_max(CP, v_ego)
      self.pid.pos_limit = steers_max
      self.pid.neg_limit = -steers_max
      steer_feedforward = self.angle_steers_des   # feedforward desired angle
      if CP.steerControlType == car.CarParams.SteerControlType.torque:
        # TODO: feedforward something based on path_plan.rateSteers
        steer_feedforward -= path_plan.angleOffset   # subtract the offset, since it does not contribute to resistive torque
        steer_feedforward *= v_ego**2  # proportional to realigning tire momentum (~ lateral accel)
      deadzone = 0.0
      output_steer = self.pid.update(self.angle_steers_des, angle_steers, check_saturation=(v_ego > 10), override=steer_override,
                                     feedforward=steer_feedforward, speed=v_ego, deadzone=deadzone)
      pid_log.active = True
      pid_log.p = self.pid.p
      pid_log.i = self.pid.i
      pid_log.f = self.pid.f
      pid_log.output = output_steer
      pid_log.saturated = bool(self.pid.saturated)

    self.sat_flag = self.pid.saturated
    return output_steer, float(self.angle_steers_des), pid_log
