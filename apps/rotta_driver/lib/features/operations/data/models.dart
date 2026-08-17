class OperationSummary {
  final String id;
  final String status;
  final String? referenceCode;
  final String? assignedAt;
  final String? origin;
  final String? destination;
  final String? loadType;
  final String? serviceLevelState;

  OperationSummary({
    required this.id,
    required this.status,
    this.referenceCode,
    this.assignedAt,
    this.origin,
    this.destination,
    this.loadType,
    this.serviceLevelState,
  });

  factory OperationSummary.fromJson(Map<String, dynamic> json) => OperationSummary(
        id: json['id'] as String,
        status: json['status'] as String,
        referenceCode: json['reference_code'] as String?,
        assignedAt: json['assigned_at'] as String?,
        origin: json['origin'] as String?,
        destination: json['destination'] as String?,
        loadType: json['load_type'] as String?,
        serviceLevelState: json['service_level_state'] as String?,
      );
}

class Stop {
  final int sequence;
  final String? stopType;
  final String? city;
  final String? state;
  final String? street;
  final String? number;
  final String? scheduledDate;
  final String? windowStart;
  final String? windowEnd;

  Stop({
    required this.sequence,
    this.stopType,
    this.city,
    this.state,
    this.street,
    this.number,
    this.scheduledDate,
    this.windowStart,
    this.windowEnd,
  });

  factory Stop.fromJson(Map<String, dynamic> json) => Stop(
        sequence: json['sequence'] as int,
        stopType: json['stop_type'] as String?,
        city: json['city'] as String?,
        state: json['state'] as String?,
        street: json['street'] as String?,
        number: json['number'] as String?,
        scheduledDate: json['scheduled_date'] as String?,
        windowStart: json['window_start'] as String?,
        windowEnd: json['window_end'] as String?,
      );
}

class Cargo {
  final String? description;
  final String? cargoType;
  final String? cargoProfile;
  final double? weightKg;
  final double? volumeM3;
  final TemperatureControl? temperatureControl;

  Cargo({
    this.description,
    this.cargoType,
    this.cargoProfile,
    this.weightKg,
    this.volumeM3,
    this.temperatureControl,
  });

  factory Cargo.fromJson(Map<String, dynamic> json) => Cargo(
        description: json['description'] as String?,
        cargoType: json['cargo_type'] as String?,
        cargoProfile: json['cargo_profile'] as String?,
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
        volumeM3: (json['volume_m3'] as num?)?.toDouble(),
        temperatureControl: json['temperature_control'] != null
            ? TemperatureControl.fromJson(json['temperature_control'] as Map<String, dynamic>)
            : null,
      );
}

class TemperatureControl {
  final double? minC;
  final double? maxC;
  final double? targetC;

  TemperatureControl({this.minC, this.maxC, this.targetC});

  factory TemperatureControl.fromJson(Map<String, dynamic> json) => TemperatureControl(
        minC: (json['min_c'] as num?)?.toDouble(),
        maxC: (json['max_c'] as num?)?.toDouble(),
        targetC: (json['target_c'] as num?)?.toDouble(),
      );
}

class TrackingInfo {
  final bool hasActiveSession;
  final String? activeSessionId;

  TrackingInfo({required this.hasActiveSession, this.activeSessionId});

  factory TrackingInfo.fromJson(Map<String, dynamic> json) => TrackingInfo(
        hasActiveSession: json['has_active_session'] as bool,
        activeSessionId: json['active_session_id'] as String?,
      );
}

class PodInfo {
  final String status;

  PodInfo({required this.status});

  factory PodInfo.fromJson(Map<String, dynamic> json) => PodInfo(
        status: json['status'] as String,
      );
}

class TimelineEvent {
  final String id;
  final String eventType;
  final String? occurredAt;
  final String? recordedAt;
  final String? actorUsername;
  final String? source;
  final Map<String, dynamic>? metadata;

  TimelineEvent({
    required this.id,
    required this.eventType,
    this.occurredAt,
    this.recordedAt,
    this.actorUsername,
    this.source,
    this.metadata,
  });

  factory TimelineEvent.fromJson(Map<String, dynamic> json) {
    final actorJson = json['actor'] as Map<String, dynamic>?;
    return TimelineEvent(
      id: json['id'] as String,
      eventType: json['event_type'] as String,
      occurredAt: json['occurred_at'] as String?,
      recordedAt: json['recorded_at'] as String?,
      actorUsername: actorJson != null ? actorJson['username'] as String? : null,
      source: json['source'] as String?,
      metadata: json['metadata'] as Map<String, dynamic>?,
    );
  }
}

class ServiceLevel {
  final String state;
  final String? plannedDeadline;
  final int? computedDelayMinutes;

  ServiceLevel({
    required this.state,
    this.plannedDeadline,
    this.computedDelayMinutes,
  });

  factory ServiceLevel.fromJson(Map<String, dynamic> json) => ServiceLevel(
        state: json['state'] as String,
        plannedDeadline: json['planned_deadline'] as String?,
        computedDelayMinutes: json['computed_delay_minutes'] as int?,
      );
}

class ThermalSummary {
  final double latestTemperatureC;
  final String latestSensorTimestamp;
  final bool validity;
  final String? quality;
  final bool? withinRange;
  final bool activeExcursion;
  final String? activeExcursionDirection;
  final String? excursionStartedAt;

  ThermalSummary({
    required this.latestTemperatureC,
    required this.latestSensorTimestamp,
    required this.validity,
    this.quality,
    this.withinRange,
    required this.activeExcursion,
    this.activeExcursionDirection,
    this.excursionStartedAt,
  });

  factory ThermalSummary.fromJson(Map<String, dynamic> json) => ThermalSummary(
        latestTemperatureC: (json['latest_temperature_c'] as num).toDouble(),
        latestSensorTimestamp: json['latest_sensor_timestamp'] as String,
        validity: json['validity'] as bool,
        quality: json['quality'] as String?,
        withinRange: json['within_range'] as bool?,
        activeExcursion: json['active_excursion'] as bool,
        activeExcursionDirection: json['active_excursion_direction'] as String?,
        excursionStartedAt: json['excursion_started_at'] as String?,
      );
}

class OperationDetail {
  final String id;
  final String status;
  final String? referenceCode;
  final Carrier? carrier;
  final DriverInfo? driver;
  final VehicleInfo? vehicle;
  final Map<String, dynamic>? origin;
  final Map<String, dynamic>? destination;
  final List<Stop> stops;
  final Cargo? cargo;
  final TrackingInfo tracking;
  final PodInfo pod;
  final String? loadType;
  final String? eta;
  final int? delayMinutes;
  final ServiceLevel? serviceLevel;
  final List<TimelineEvent> timeline;
  final ThermalSummary? thermalSummary;

  OperationDetail({
    required this.id,
    required this.status,
    this.referenceCode,
    this.carrier,
    this.driver,
    this.vehicle,
    this.origin,
    this.destination,
    required this.stops,
    this.cargo,
    required this.tracking,
    required this.pod,
    this.loadType,
    this.eta,
    this.delayMinutes,
    this.serviceLevel,
    required this.timeline,
    this.thermalSummary,
  });

  factory OperationDetail.fromJson(Map<String, dynamic> json) => OperationDetail(
        id: json['id'] as String,
        status: json['status'] as String,
        referenceCode: json['reference_code'] as String?,
        carrier: json['carrier'] != null ? Carrier.fromJson(json['carrier'] as Map<String, dynamic>) : null,
        driver: json['driver'] != null ? DriverInfo.fromJson(json['driver'] as Map<String, dynamic>) : null,
        vehicle: json['vehicle'] != null ? VehicleInfo.fromJson(json['vehicle'] as Map<String, dynamic>) : null,
        origin: json['origin'] as Map<String, dynamic>?,
        destination: json['destination'] as Map<String, dynamic>?,
        stops: (json['stops'] as List<dynamic>).map((e) => Stop.fromJson(e as Map<String, dynamic>)).toList(),
        cargo: json['cargo'] != null ? Cargo.fromJson(json['cargo'] as Map<String, dynamic>) : null,
        tracking: TrackingInfo.fromJson(json['tracking'] as Map<String, dynamic>),
        pod: PodInfo.fromJson(json['pod'] as Map<String, dynamic>),
        loadType: json['load_type'] as String?,
        eta: json['eta'] as String?,
        delayMinutes: json['delay_minutes'] as int?,
        serviceLevel: json['service_level'] != null ? ServiceLevel.fromJson(json['service_level'] as Map<String, dynamic>) : null,
        timeline: json['timeline'] != null
            ? (json['timeline'] as List<dynamic>).map((e) => TimelineEvent.fromJson(e as Map<String, dynamic>)).toList()
            : [],
        thermalSummary: json['thermal_summary'] != null ? ThermalSummary.fromJson(json['thermal_summary'] as Map<String, dynamic>) : null,
      );
}

class Carrier {
  final String id;
  final String? tradeName;

  Carrier({required this.id, this.tradeName});

  factory Carrier.fromJson(Map<String, dynamic> json) => Carrier(
        id: json['id'] as String,
        tradeName: json['trade_name'] as String?,
      );
}

class DriverInfo {
  final String id;
  final String? fullName;

  DriverInfo({required this.id, this.fullName});

  factory DriverInfo.fromJson(Map<String, dynamic> json) => DriverInfo(
        id: json['id'] as String,
        fullName: json['full_name'] as String?,
      );
}

class VehicleInfo {
  final String? id;
  final String? plate;

  VehicleInfo({this.id, this.plate});

  factory VehicleInfo.fromJson(Map<String, dynamic> json) => VehicleInfo(
        id: json['id'] as String?,
        plate: json['plate'] as String?,
      );
}
