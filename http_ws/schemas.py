from marshmallow import Schema, fields, validate


class ItemResponseSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str()
    company = fields.Str(allow_none=True)
    title = fields.Str(allow_none=True)
    content = fields.Str(allow_none=True)

    client_img_filename = fields.Str(allow_none=True)
    client_img_width = fields.Int(allow_none=True)
    client_img_height = fields.Int(allow_none=True)

    categories = fields.List(fields.Int())
    available = fields.Bool()
    created_at = fields.Str()

class CreateBookingRequestSchema(Schema):
    disk_name = fields.Str(required=True)
    start_ts = fields.DateTime(required=True)
    duration = fields.Int(required=True)

class BookingResponseSchema(Schema):
    id = fields.Int(required=True)
    disk_name = fields.Str(required=True)
    start_ts = fields.DateTime(required=True)
    end_ts = fields.DateTime(required=False)

class OkStatusResponseSchema(Schema):
    ok = fields.Bool(required=True)
    status = fields.Str(required=True)

class StopBookingRequestSchema(Schema):
    disk_name = fields.Str(required=True)

class OccupiedTimesRequestSchema(Schema):
    disk_id = fields.Int(required=False)
    date = fields.Date(required=True)

class OccupiedIntervalSchema(Schema):
    start = fields.DateTime(required=True)
    end = fields.DateTime(required=True)

class OccupiedTimesResponseSchema(Schema):
    date = fields.Date(required=True)
    disk_id = fields.Int(allow_none=True)
    occupied = fields.Nested(OccupiedIntervalSchema, many=True, required=True)

class StatusResponseSchema(Schema):
    status = fields.Str(required=True, dump_default="confirmed")

class SimpleResponseSchema(Schema):
    ok = fields.Bool(required=True)

class ItemCreateRequestSchema(Schema):
    name = fields.Str(required=True)
    company = fields.Str(required=True)
    title = fields.Str(required=True)
    content = fields.Str(required=True)

    categories = fields.Str(required=True)

    client_img = fields.Raw(
        metadata={"type": "string", "format": "binary"}
    )
