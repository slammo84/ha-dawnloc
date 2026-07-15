# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
import json, logging, os, sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import __version__
from .locator import Locator
from .mqtt_worker import MQTTWorker
from .parser import is_mac
from .store import Store

DEFAULT_OPTIONS={"raw_topic":"dawnloc/raw/hearing_map","sample_ttl_seconds":20,"offline_after_seconds":300,"stable_seconds":60,"sample_window":7,"min_shared_aps":2,"room_hold_seconds":60,"switch_confidence":70,"single_ap_threshold":-58,"log_level":"info"}
@dataclass(frozen=True)
class Settings:
    values:dict[str,Any]
    @classmethod
    def load(cls):
        p=Path(os.environ.get("DAWNLOC_OPTIONS","/data/options.json")); v=DEFAULT_OPTIONS.copy()
        if p.exists(): v.update(json.loads(p.read_text(encoding="utf-8")))
        return cls(v)
SETTINGS=Settings.load(); logging.basicConfig(level=getattr(logging,str(SETTINGS.values['log_level']).upper(),logging.INFO),format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STORE=Store(os.environ.get("DAWNLOC_DB","/data/dawnloc.db"))
LOCATOR=Locator(STORE,ttl_seconds=int(SETTINGS.values['sample_ttl_seconds']),offline_after=int(SETTINGS.values['offline_after_seconds']),stable_seconds=int(SETTINGS.values['stable_seconds']),sample_window=int(SETTINGS.values['sample_window']),min_shared_aps=int(SETTINGS.values['min_shared_aps']),room_hold_seconds=int(SETTINGS.values['room_hold_seconds']),switch_confidence=float(SETTINGS.values['switch_confidence']),single_ap_threshold=float(SETTINGS.values['single_ap_threshold']))
MQTT=MQTTWorker(STORE,LOCATOR,host=os.environ.get("MQTT_HOST","localhost"),port=int(os.environ.get("MQTT_PORT","1883")),username=os.environ.get("MQTT_USERNAME"),password=os.environ.get("MQTT_PASSWORD"),raw_topic=str(SETTINGS.values['raw_topic']))
STATIC_DIR=Path(__file__).parent/'static'; INDEX_HTML=(STATIC_DIR/'index.html').read_text(encoding='utf-8')
@asynccontextmanager
async def lifespan(app:FastAPI)->AsyncIterator[None]:
    MQTT.start(); yield; MQTT.stop(); STORE.close()
app=FastAPI(title='DAWNLoc',version=__version__,lifespan=lifespan); app.mount('/assets',StaticFiles(directory=STATIC_DIR),name='assets')
class DeviceInput(BaseModel):
    mac:str; name:str=Field(min_length=1,max_length=80); slug:str|None=None; device_type:str='tracked'; reference_room_slug:str|None=None
class RoomInput(BaseModel): name:str=Field(min_length=1,max_length=80); slug:str|None=None
class NameInput(BaseModel): name:str=Field(min_length=1,max_length=80)
class APInput(BaseModel): room_slug:str|None=None
class CalibrationInput(BaseModel): device_mac:str; room_slug:str; duration:int=Field(default=25,ge=5,le=120)
@app.get('/',response_class=HTMLResponse)
def index(): return INDEX_HTML
@app.get('/health')
def health(): return {'status':'ok','mqtt_connected':MQTT.connected}
@app.get('/api/status')
def status():
    aps=LOCATOR.discovered()['access_points']; grouped={}
    for ap in aps: grouped.setdefault(ap['hostname'],0.0); grouped[ap['hostname']]=min(grouped[ap['hostname']] or ap['age_seconds'],ap['age_seconds'])
    return {'mqtt_connected':MQTT.connected,'access_points':[{'hostname':k,'age_seconds':v} for k,v in sorted(grouped.items())]}
@app.get('/api/live')
def live(): return LOCATOR.list_states()
@app.get('/api/discovered')
def discovered():
    data=LOCATOR.discovered(); configured={d['mac'] for d in STORE.list_devices()}; data['clients']=[dict(c,configured=c['mac'] in configured) for c in data['clients'] if c['locatable']]; return data
@app.get('/api/devices')
def devices(): return STORE.list_devices()
@app.post('/api/devices')
def add_device(item:DeviceInput):
    if not is_mac(item.mac): raise HTTPException(400,'errors.invalid_mac')
    try: d=STORE.upsert_device(item.mac,item.name,item.slug,item.device_type,item.reference_room_slug)
    except (sqlite3.IntegrityError,ValueError) as e: raise HTTPException(409,str(e)) from e
    MQTT.sync_discovery(); MQTT.publish_device_state(d); return d
@app.patch('/api/devices/{mac}')
def rename_device(mac:str,item:NameInput):
    d=STORE.rename_device(mac,item.name)
    if not d: raise HTTPException(404,'errors.device_not_found')
    MQTT.sync_discovery(); MQTT.publish_device_state(d); return d
@app.delete('/api/devices/{mac}')
def delete_device(mac:str):
    d=STORE.get_device(mac)
    if not d: raise HTTPException(404,'errors.device_not_found')
    STORE.delete_device(mac); MQTT.remove_device(d); return {'ok':True}
@app.get('/api/rooms')
def rooms(): return STORE.list_rooms()
@app.post('/api/rooms')
def add_room(item:RoomInput): return STORE.upsert_room(item.name,item.slug)
@app.patch('/api/rooms/{slug}')
def rename_room(slug: str, item: NameInput):
    room = STORE.rename_room(slug, item.name)
    if room is None:
        raise HTTPException(404, 'errors.room_not_configured')
    return room
@app.delete('/api/rooms/{slug}')
def delete_room(slug:str): STORE.delete_room(slug); return {'ok':True}
@app.get('/api/access-point-rooms')
def ap_rooms(): return STORE.list_access_point_rooms()
@app.put('/api/access-point-rooms/{hostname}')
def set_ap_room(hostname:str,item:APInput): return STORE.set_access_point_room(hostname,item.room_slug)
@app.get('/api/fingerprints')
def fingerprints(): return STORE.list_fingerprints()
@app.delete('/api/fingerprints/{fid}')
def delete_fp(fid:int): STORE.delete_fingerprint(fid); return {'ok':True}
@app.post('/api/calibrations/start')
def start_cal(item:CalibrationInput):
    try: s=LOCATOR.start_calibration(item.device_mac,item.room_slug,item.duration)
    except ValueError as e: raise HTTPException(400,str(e)) from e
    return LOCATOR.calibration_status(s.id) or {}
@app.get('/api/calibrations/{sid}')
def cal_status(sid:str):
    r=LOCATOR.calibration_status(sid)
    if r is None: raise HTTPException(404,'errors.calibration_not_found')
    return r
@app.get('/api/export/{kind}')
def export(kind:str):
    if kind not in {'devices','fingerprints','all'}: raise HTTPException(400,'invalid export type')
    payload={'format':'dawnloc-export','format_version':1,'app_version':__version__,'created_at':datetime.now(UTC).isoformat(),'data':STORE.export_data(kind)}
    return JSONResponse(payload,headers={'Content-Disposition':f'attachment; filename="dawnloc-{kind}.json"'})
@app.post('/api/import')
async def import_file(file:UploadFile=File(...)):
    try: payload=json.loads((await file.read()).decode('utf-8'))
    except Exception as e: raise HTTPException(400,'invalid JSON file') from e
    if payload.get('format')!='dawnloc-export' or payload.get('format_version')!=1: raise HTTPException(400,'unsupported export format')
    try: counts=STORE.import_data(payload.get('data') or {})
    except Exception as e: raise HTTPException(400,str(e)) from e
    MQTT.sync_discovery(); MQTT.publish_all_states(); return {'ok':True,'imported':counts}
def run(): uvicorn.run(app,host='0.0.0.0',port=8099,proxy_headers=True)
if __name__=='__main__': run()
