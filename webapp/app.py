import os
import sys
import time
import base64
import imghdr
import random
from datetime import timedelta
from collections import OrderedDict

import cv2
import khandy
import numpy as np
import requests
from flask import Flask
from flask import request
from flask import render_template
from werkzeug.utils import secure_filename
from gevent.pywsgi import WSGIServer

sys.path.insert(0, '..')
import plantid


app = Flask(__name__)
app.send_file_max_age_default = timedelta(seconds=1)
plant_identifier = plantid.PlantIdentifier()

MIN_IMAGE_SIZE_LENGTH = 16
MAX_IMAGE_SIZE_LENGTH = 5160


def imread_ex(filename, flags=-1):
    try:
        return cv2.imdecode(np.fromfile(filename, dtype=np.uint8), flags)
    except Exception as e:
        return None
        
        
def identify(image, topk=5):
    if image is None:
        return {"status": 1102, 
                "message": "Image parsing error!", 
                "results": [], 
                "family_results": [], 
                "genus_results": []}
    if image.dtype != np.uint8:
        return {"status": 1103, 
                "message": "Image data type error, only support uint8 data type.", 
                "results": [], 
                "family_results": [], 
                "genus_results": []}
    if max(image.shape[:2]) > MAX_IMAGE_SIZE_LENGTH or min(image.shape[:2]) < MIN_IMAGE_SIZE_LENGTH:
        return {"status": 1104, 
                "message": "Image size error, shorter edge must >= {}px, longer edge must <= {}px".format(
                           MIN_IMAGE_SIZE_LENGTH, MAX_IMAGE_SIZE_LENGTH), 
                "results": [], 
                "family_results": [], 
                "genus_results": []}

    outputs = plant_identifier.identify(image, topk=topk)
    if outputs['status'] == -1:
        return {"status": 1105, 
                "message": "Image preprocess error.", 
                "results": [], 
                "family_results": [], 
                "genus_results": []}
    elif outputs['status'] == -2:
        return {"status": 1106, 
                "message": "Inference error.",
                "results": [], 
                "family_results": [], 
                "genus_results": []}
                
    return {"status": 0, 
            "message": "OK", 
            "results": outputs['results'],
            "family_results": outputs['family_results'], 
            "genus_results": outputs['genus_results']}


@app.route('/api/plant', methods=['POST'])
def identify_api():
    base_dir = os.path.dirname(__file__)
    image_dir = os.path.join(base_dir, 'static/api_images')
    os.makedirs(image_dir, exist_ok=True)
    
    if request.form.get('image'):
        try:
            image_bytes = base64.b64decode(request.form['image'])
            extension = imghdr.what('', image_bytes)
            time_stamp = int(round(time.time() * 1000))
            new_image_filename = '{}_{:05d}.{}'.format(time_stamp, random.randint(0, 99999), extension)
            raw_image_filename = os.path.join(image_dir, new_image_filename)
            with open(raw_image_filename, "wb") as f:
                f.write(image_bytes)
            image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), -1)
        except Exception as e:
            return {"status": 1201, 
                    "message": 'Image content error: {}'.format(e), 
                    "results": [], 
                    "family_results": [], 
                    "genus_results": []}
        return identify(image, topk=3)
    else:
        return {"status": 1202, 
                "message": "Parameter Error", 
                "results": [],
                "family_results": [], 
                "genus_results": []}


def allowed_file_type(filename):
    ALLOWED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.bmp']
    extension = os.path.splitext(os.path.basename(filename))[1]
    return extension.lower() in ALLOWED_EXTENSIONS


@app.route('/', methods=['POST', 'GET'])
def main():
    base_dir = os.path.dirname(__file__)
    raw_image_dir = os.path.join(base_dir, 'static/raw_images')
    tmp_image_dir = os.path.join(base_dir, 'static/images')
    os.makedirs(raw_image_dir, exist_ok=True)
    os.makedirs(tmp_image_dir, exist_ok=True)
    
    time_stamp = int(round(time.time() * 1000))
    if request.method == 'POST':
        image_fs = request.files['image']
        if image_fs:
            image_filename = os.path.basename(secure_filename(image_fs.filename))
            extension = os.path.splitext(image_filename)[-1]
            new_image_filename = '{}_{:05d}{}'.format(time_stamp, random.randint(0, 99999), extension)
            raw_image_filename = os.path.join(raw_image_dir, new_image_filename)  
            image_fs.save(raw_image_filename)
        else:
            try:
                response = requests.get(request.form['image_url'], timeout=30)
                extension = imghdr.what('', response.content)
                if extension is None:
                   raise Exception('not an image URL!')
                new_image_filename = '{}_{:05d}.{}'.format(time_stamp, random.randint(0, 99999), extension)
                raw_image_filename = os.path.join(raw_image_dir, new_image_filename)
                with open(raw_image_filename, "wb") as f:
                    f.write(response.content)
            except Exception as e:
                outputs = {"status": 1001, 
                           "message": 'Image download error: {}'.format(e), 
                           "results": [], 
                           "family_results": [], 
                           "genus_results": []}
                return render_template('upload_error.html', 
                                       status=outputs['status'], 
                                       message=outputs['message'],
                                       image_filename='', 
                                       timestamp=time.time())

        if not allowed_file_type(new_image_filename):
            extension = os.path.splitext(new_image_filename)[-1]
            outputs = {"status": 1002, 
                        "message": "Image file format error, only support png, jpg, jpeg, bmp, got {}".format(extension), 
                        "results": [], 
                        "family_results": [], 
                        "genus_results": []}
            return render_template('upload_error.html', 
                                   status=outputs['status'], 
                                   message=outputs['message'],
                                   image_filename='', 
                                   timestamp=time.time())
            
        image = imread_ex(raw_image_filename, -1)
        outputs = identify(image)
        if outputs['status'] == 0:
            if min(image.shape[:2]) > 512:
                image = khandy.resize_image_short(image, 512)
            cv2.imwrite(os.path.join(tmp_image_dir, new_image_filename), image)
            labels = ['Chinese Name', 'Latin Name', 'Confidence']
            return render_template('upload_ok.html', 
                                   labels=labels, 
                                   results=outputs['results'], 
                                   family_results=outputs['family_results'], 
                                   genus_results=outputs['genus_results'], 
                                   image_filename=new_image_filename, 
                                   timestamp=time.time())
        else:
            return render_template('upload_error.html', 
                                   status=outputs['status'], 
                                   message=outputs['message'],
                                   image_filename='', 
                                   timestamp=time.time())
    return render_template('upload.html')
    
    
if __name__ == '__main__':
    app.run(port=5000, debug=False)
    
    # http_server = WSGIServer(('0.0.0.0', 5000), app)
    # http_server.serve_forever()
