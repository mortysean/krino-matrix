"""3D 形象：用户上传的 VRM 模型（存在数据库里），以及给角色选用哪个模型。

上传检查：大小上限、glTF 二进制头、必须带 VRM 扩展（VRM 0.x 的 VRM 或 1.0 的 VRMC_vrm）。
模型作者写在文件里的许可信息原样保存并展示给用户；默认形象是 pixiv 的 VRM 示例模型（见 frontend/assets/vrm/LICENSE.md）。
"""
from __future__ import annotations

import hashlib
import json
import struct

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .config import settings
from .db import get_db
from .models import AvatarModel, Character, User
from .personas import get_owned

router = APIRouter(prefix="/api", tags=["avatars"])
MAX_PER_USER = 10


class VRMError(ValueError):
    pass


def inspect_vrm(data: bytes) -> tuple[str, dict]:
    """返回 (VRM 版本, 元数据)。只读 JSON 块，不执行任何东西。"""
    if len(data) < 20 or data[:4] != b"glTF":
        raise VRMError("不是 glTF 二进制文件（.vrm / .glb）")
    version, length = struct.unpack("<II", data[4:12])
    if version != 2 or length > len(data):
        raise VRMError("只支持 glTF 2.0")
    chunk_len, chunk_type = struct.unpack("<II", data[12:20])
    if chunk_type != 0x4E4F534A or chunk_len > len(data) - 20:  # "JSON"
        raise VRMError("文件结构不对")
    try:
        doc = json.loads(data[20:20 + chunk_len])
    except ValueError as e:
        raise VRMError("文件里的 JSON 损坏") from e
    ext = doc.get("extensions") or {}
    if "VRMC_vrm" in ext:
        meta = ext["VRMC_vrm"].get("meta") or {}
        return "1.0", {"name": meta.get("name"), "authors": meta.get("authors"), "license": meta.get("licenseUrl"),
                       "redistribution": meta.get("allowRedistribution"), "copyright": meta.get("copyrightInformation")}
    if "VRM" in ext:
        meta = ext["VRM"].get("meta") or {}
        return "0.x", {"name": meta.get("title"), "authors": [meta.get("author")] if meta.get("author") else [],
                       "license": meta.get("licenseName") or meta.get("otherLicenseUrl"),
                       "redistribution": None, "copyright": None}
    raise VRMError("这是普通的 glTF，不是 VRM 模型")


def model_out(m: AvatarModel) -> dict:
    return {"id": m.id, "name": m.name, "size": m.size, "vrm_version": m.vrm_version, "meta": m.meta,
            "created_at": m.created_at.isoformat()}


@router.get("/avatars")
def list_models(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AvatarModel).where(AvatarModel.user_id == user.id).order_by(AvatarModel.created_at))
    return [model_out(m) for m in rows]


@router.post("/avatars")
async def upload(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith((".vrm", ".glb")):
        raise HTTPException(415, "只支持 .vrm 文件")
    data = await file.read(settings.vrm_max_bytes + 1)
    if len(data) > settings.vrm_max_bytes:
        raise HTTPException(413, f"模型不能超过 {settings.vrm_max_bytes // 1024 // 1024} MB")
    try:
        version, meta = inspect_vrm(data)
    except VRMError as e:
        raise HTTPException(400, str(e)) from e
    sha = hashlib.sha256(data).hexdigest()
    same = db.scalar(select(AvatarModel).where(AvatarModel.user_id == user.id, AvatarModel.sha256 == sha))
    if same:
        return model_out(same)
    if len(list_models(user, db)) >= MAX_PER_USER:
        raise HTTPException(400, f"最多保存 {MAX_PER_USER} 个模型")
    m = AvatarModel(user_id=user.id, name=str(meta.get("name") or file.filename)[:80], sha256=sha, size=len(data),
                    vrm_version=version, meta=meta, data=data)
    db.add(m)
    db.commit()
    return model_out(m)


@router.get("/avatars/{mid}/file")
def download(mid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(AvatarModel, mid)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "模型不存在")
    return Response(m.data, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/avatars/{mid}")
def remove(mid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(AvatarModel, mid)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "模型不存在")
    db.execute(Character.__table__.update().where(Character.avatar_model_id == mid).values(avatar_model_id=None))
    db.delete(m)
    db.commit()
    return {"ok": True}


class ChooseIn(BaseModel):
    model_id: str | None = None


@router.put("/characters/{cid}/avatar")
def choose(cid: str, body: ChooseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """给角色换 3D 形象（None = 默认形象）。这是你自己的偏好，不会进人设包。"""
    c = get_owned(db, user, cid)
    if body.model_id:
        m = db.get(AvatarModel, body.model_id)
        if m is None or m.user_id != user.id:
            raise HTTPException(404, "模型不存在")
    c.avatar_model_id = body.model_id
    db.commit()
    return {"ok": True, "avatar_model_id": c.avatar_model_id}
