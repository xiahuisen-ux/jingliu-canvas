"""Read-only model labels and readiness, without loading models or making API calls."""
def catalog(st):
    text=st.text_models.public();image=st.single_image_edit.status(st.director.CFG);edit=st.character_image_edit.status(st.director.CFG)
    video=st.h3_native.status();face=st.face_refine.status();lips=st.musetalk_backend.status();settings=st.load_settings()
    cloud=text.get('provider')!='local'
    text_state=('已配置 · 云端' if text.get('key_configured') else '待配置密钥') if cloud else '已选择 · 本地'
    return [
      {'category':'文字模型','models':[{'name':text.get('model') or '未选择','state':text_state,'ready':bool(text.get('key_configured')) if cloud else None}]},
      {'category':'图片模型','models':[{'name':image.get('model','Z-Image-Turbo'),'state':'可用 · 生图' if image.get('ready') else '未就绪 · 生图','ready':bool(image.get('ready'))},{'name':edit.get('model','Qwen-Image-Edit-2511'),'state':'可用 · 重绘' if edit.get('ready') else '未就绪 · 重绘','ready':bool(edit.get('ready'))}]},
      {'category':'视频模型','models':[{'name':'MiniMax H3 · h3.c Metal','state':'可用' if video.get('ready') else '未就绪','ready':bool(video.get('ready'))}]},
      {'category':'面部模型','models':[{'name':'H3 FaceRefine','state':('可用 · 自动开启' if settings.get('h3c_face_refine') else '可用 · 自动关闭') if face.get('ready') else '未就绪','ready':bool(face.get('ready'))}]},
      {'category':'对口型模型','models':[{'name':lips.get('model','MuseTalk 1.5'),'state':('可用' if lips.get('validated') else '已安装 · 效果待验证') if lips.get('ready') else '未就绪','ready':bool(lips.get('ready'))}]}]
