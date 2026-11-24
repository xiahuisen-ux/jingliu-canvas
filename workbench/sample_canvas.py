"""Install the redistributable, model-free demo in the native graph format."""
import json
from pathlib import Path
import shutil
import tempfile

def install_sample(st):
    target = st.PROJECTS / 'sunset-demo'
    marker = st.DATA / '.sample-initialized'
    if marker.exists() or any(st.PROJECTS.glob('*/project.json')):
        marker.touch(exist_ok=True)
        return
    files = Path(__file__).resolve().parents[1] / 'web' / 'demo'
    with tempfile.TemporaryDirectory(dir=st.DATA) as work:
        folder = Path(work) / target.name
        folder.mkdir()
        st.project_storage.initialize(folder, '落日航行')
        shutil.copytree(files, folder / 'demo')
        p = dict(id=target.name, title='落日航行 · 画布操作示例', brief='', stage='brief',
                 created_at=st.now(), updated_at=st.now(), shots=[], uploads=[], assets={},
                 analysis={'locations':[], 'key_objects':[], 'characters':[]})
        positions = {}
        for i,(name, title, kind) in enumerate([('boat','帆船形态','key_objects'),('coast','海岸层次','locations'),('sun','落日色调','locations')]):
            path = f'demo/{name}.jpg'
            p['analysis'][kind].append(dict(id=name,name=title,custom=True,canvas_image=True,canvas_status='初始',canvas_prompt=''))
            p['assets'][name] = {'images':[path], 'selected_images':[path]}
            positions['asset:'+name]={'x':80,'y':60+i*320}
        clip = st.canvas_videos.blank(st, '落日航行', 5)
        clip.update(id='sail',video='demo/sail.mp4',status='video_ready',canvas_request='小帆船驶过落日下的海面。',element_ids=['boat','coast'],auto_elements=False,use_element_references=True,generation_mode='omni_reference')
        positions['clip:sail']={'x':650,'y':210}
        p.update(canvas_videos=[clip], canvas_workspace={'positions':positions,'viewport':{'x':40,'y':30,'zoom':0.63}})
        (folder/'project.json').write_text(json.dumps(p,ensure_ascii=False),encoding='utf-8')
        folder.rename(target)
    marker.touch()
