import math
from selfdrive.controls.lib.pid import PIDController
from selfdrive.controls.lib.drive_helpers import get_steer_max
from cereal import log
from selfdrive.kegman_kans_conf import kegman_kans_conf


class LatControlPID():
  def __init__(self, CP, CI):
    self.kegman_kans = kegman_kans_conf(CP)
    self.deadzone = float(self.kegman_kans.conf['deadzone'])
    self.pid = PIDController((CP.lateralTuning.pid.kpBP, CP.lateralTuning.pid.kpV),
                            (CP.lateralTuning.pid.kiBP, CP.lateralTuning.pid.kiV),
                            (CP.lateralTuning.pid.kdBP, CP.lateralTuning.pid.kdV),
                            k_f=CP.lateralTuning.pid.kf, pos_limit=1.0, neg_limit=-1.0,
                            sat_limit=CP.steerLimitTimer, derivative_period=0.1)
    self.get_steer_feedforward = CI.get_steer_feedforward_function()
    self.mpc_frame = 0

  def reset(self):
    self.pid.reset()

  def live_tune(self, CP):
    self.mpc_frame += 1
    if self.mpc_frame % 300 == 0:
      # live tuning through /data/openpilot/tune.py overrides interface.py settings
      self.kegman_kans = kegman_kans_conf()
      if self.kegman_kans.conf['tuneGernby'] == "1":
        self.steerKpV = [float(self.kegman_kans.conf['Kp'])]
        self.steerKiV = [float(self.kegman_kans.conf['Ki'])]
        self.steerKdV = [float(self.kegman_kans.conf['Kd'])]
        self.steerKf = float(self.kegman_kans.conf['Kf'])
        self.steerLimitTimer = float(self.kegman_kans.conf['steerLimitTimer'])
        self.pid = PIDController((CP.lateralTuning.pid.kpBP, self.steerKpV),
                            (CP.lateralTuning.pid.kiBP, self.steerKiV),
                            (CP.lateralTuning.pid.kdBP, self.steerKdV),
                            k_f=self.steerKf, pos_limit=1.0, neg_limit=-1.0,
                            sat_limit=self.steerLimitTimer, derivative_period=0.1)
        self.deadzone = float(self.kegman_kans.conf['deadzone'])

      self.mpc_frame = 0

  def update(self, active, CS, CP, VM, params, last_actuators, desired_curvature, desired_curvature_rate):
    self.live_tune(CP)
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)

    angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
    angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg

    pid_log.steeringAngleDesiredDeg = angle_steers_des
    pid_log.angleError = angle_steers_des - CS.steeringAngleDeg
    if CS.vEgo < 0.3 or not active:
      output_steer = 0.0
      pid_log.active = False
      self.pid.reset()
    else:
      steers_max = get_steer_max(CP, CS.vEgo)
      self.pid.pos_limit = steers_max
      self.pid.neg_limit = -steers_max

      # offset does not contribute to resistive torque
      steer_feedforward = self.get_steer_feedforward(angle_steers_des_no_offset, CS.vEgo)

      deadzone = self.deadzone

      check_saturation = (CS.vEgo > 10) and not CS.steeringRateLimited and not CS.steeringPressed
      output_steer = self.pid.update(angle_steers_des, CS.steeringAngleDeg, check_saturation=check_saturation, override=CS.steeringPressed,
                                     feedforward=steer_feedforward, speed=CS.vEgo, deadzone=deadzone)
      pid_log.active = True
      pid_log.p = self.pid.p
      pid_log.i = self.pid.i
      pid_log.f = self.pid.f
      pid_log.output = output_steer
      pid_log.saturated = bool(self.pid.saturated)

    return output_steer, angle_steers_des, pid_log
