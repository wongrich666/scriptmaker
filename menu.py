from flask import Blueprint, render_template
from flask_login import login_required
import os
import logging

menu = Blueprint('menu', __name__)

@menu.route('/menu')
@login_required
def index():
    return render_template('menu.html')

@menu.route('/text_generation')
@login_required
def text_generation():
    return render_template('text_generation.html')

@menu.route('/script_generation')
@login_required
def script_generation():
    return render_template('script_generation.html') 