import requests
import json
import ast
import pandas as pd
from datetime import datetime, timedelta
from Data_Parser_Examples import (
    parseHydroRangerPayload,
    parseThetaPayload,
    parseECHOdata,
    parseDROPLETdata,
    parseHYGROdata,
)

# Endpoints
BASE_BOUNDS = "https://a8p8m605b5.execute-api.eu-west-2.amazonaws.com/sepa_iot_device_date_bounds"
BASE_FETCH = "https://oujshf1m2h.execute-api.eu-west-2.amazonaws.com/tekh_dataFetch"

# Load device config
with open("tekh_devices.json") as f:
    devices = json.load(f)

def get_device_info(device_eui):
    for d in devices:
        if d["DeviceEUI"] == device_eui:
            return d
    raise ValueError(f"DeviceEUI {device_eui} not found in tekh_devices.json")

def parse_payload(device_type, payload, empty_distance=None):
    try:
        if device_type == "HydroRanger":
            if len(bytes.fromhex(payload)) == 13:
                return parseHydroRangerPayload(payload, emptyDist=int(empty_distance))
        elif device_type == "Theta":
            return parseThetaPayload(payload)
        elif device_type == "Echo":
            return parseECHOdata(payload, emptyDist=int(empty_distance))
        elif device_type == "Droplet":
            return parseDROPLETdata(payload)
        elif device_type == "Hygro":
            return parseHYGROdata(payload)
    except Exception as e:
        return {"error": str(e)}
    return {"note": "unparsed/short payload"}

def fetch_new_data(device_eui, existing_csv_path):
    """
    Fetch new data from the API for a device, starting from the last timestamp
    in the existing CSV, using the SAME column structure as full-history pulls.
    """

    # Load existing CSV
    df_existing = pd.read_csv(existing_csv_path)

    # Robust timestamp parsing
    df_existing["timestamp"] = pd.to_datetime(df_existing["timestamp"], errors="coerce")
    last_ts = df_existing["timestamp"].max()

    info = get_device_info(device_eui)
    device_type = info["type"]
    empty_distance = info.get("EmptyDistance")

    all_records = []
    ts = last_ts + timedelta(seconds=1)

    # Fetch bounds
    bounds = requests.get(BASE_BOUNDS,
                          params={"device": device_eui, "type": device_type}).json()
    end = datetime.fromisoformat(bounds["endTS"].replace("Z", "+00:00"))

    # Fetch loop
    while ts < end:
        resp = requests.get(
            BASE_FETCH,
            params={
                "device": device_eui,
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "type": device_type
            }
        )
        data = resp.json()

        if not data:
            break

        for rec in data:
            parsed = parse_payload(device_type, rec["Payload"], empty_distance)

            rec_out = {
                "timestamp": rec["TimeStamp"],
                "device_eui": rec["DevEUI"],
                "device_name": info["DevName"],
                "device_type": device_type,
                "site_name": info["SiteName"],
                "latitude": float(info["Lat"]),
                "longitude": float(info["Lon"]),
                "payload": rec["Payload"],
            }

            # Metadata handling
            try:
                rec_out["metadata"] = (
                    ast.literal_eval(rec["Metadata"])
                    if rec.get("Metadata") else None
                )
            except Exception:
                rec_out["metadata"] = rec.get("Metadata", None)

            # Expand parsed fields (IDENTICAL to full history)
            if parsed and not isinstance(parsed, dict):
                if device_type == "Droplet":
                    rec_out.update({
                        "air_temp": parsed[0],
                        "air_pressure": parsed[1],
                        "air_humidity": parsed[2],
                        "battery_volt": parsed[3],
                        "rtc_temp": parsed[4],
                        "rainfall": parsed[5],
                        "status": parsed[6]
                    })

                elif device_type == "Hygro":
                    rec_out.update({
                        "soil_moisture": parsed[0],
                        "soil_temp": parsed[1],
                        "soil_conductivity": parsed[2],
                        "air_temp": parsed[3],
                        "air_humidity": parsed[4],
                        "battery_volt": parsed[5],
                        "status": parsed[6]
                    })

            all_records.append(rec_out)

        # Update timestamp cursor
        last_ts_api = datetime.fromisoformat(data[-1]["TimeStamp"].replace("Z", "+00:00"))
        ts = last_ts_api + timedelta(seconds=1)

    # Convert to DataFrame
    df_new = pd.DataFrame(all_records)
    if df_new.empty:
        print("No new data available.")
        return df_existing

    # Parse timestamp & sort
    df_new["timestamp"] = pd.to_datetime(df_new["timestamp"], errors="coerce")

    # Combine, dedupe, save back
    df_combined = (
        pd.concat([df_existing, df_new], ignore_index=True)
        .drop_duplicates(subset=["timestamp", "device_eui"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    df_combined.to_csv("data/training_data_droplet.csv", index=False)
    # df_combined.to_csv("data/training_data_hygro.csv", index=False)

    print(f"Appended {len(df_new)} new rows to {existing_csv_path}")
    return df_combined


df_droplet = fetch_new_data("70B3D5499AFA2DEE", "data/Droplet_2_70B3D5499AFA2DEE_365days.csv")

#df_hygro = fetch_new_data("70B3D51C20000090", "data/Hygro00:90_70B3D51C20000090_365days.csv")