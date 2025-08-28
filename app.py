from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from PIL import Image
import json
import os
import time

app = Flask(__name__)

# --- Production Configuration ---
# Use environment variables for sensitive data. Use defaults for local development.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-default-dev-secret-key')

# Define a persistent data directory for Render.
# RENDER_DISK_PATH is an environment variable that Render sets.
DATA_DIR = os.environ.get('RENDER_DISK_PATH', 'instance')
app.config['UPLOAD_FOLDER'] = os.path.join(DATA_DIR, 'uploads')
PRODUCTS_FILE = os.path.join(DATA_DIR, 'products.json')
CATEGORIES_FILE = os.path.join(DATA_DIR, 'categories.json')

# Ensure the upload and data folders exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id):
        self.id = id

    def get_id(self):
        return str(self.id)

# Use environment variables for admin credentials
ADMIN_USER = {
    "username": os.environ.get('ADMIN_USERNAME', 'admin'),
    "password": os.environ.get('ADMIN_PASSWORD', 'admin')
}

@login_manager.user_loader
def load_user(user_id):
    if user_id == ADMIN_USER["username"]:
        return User(ADMIN_USER["username"])
    return None

def save_image(file_storage, output_folder, basename):
    """Saves an image, converting to WebP if supported."""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    original_filename = secure_filename(file_storage.filename)
    original_extension = os.path.splitext(original_filename)[1].lower()
    supported_formats_for_conversion = ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']

    if original_extension in supported_formats_for_conversion:
        webp_filename = f"{basename}.webp"
        webp_filepath = os.path.join(output_folder, webp_filename)
        try:
            image = Image.open(file_storage)
            if image.mode in ('P', 'PA'):
                image = image.convert("RGBA")
            image.save(webp_filepath, 'webp', quality=85)
            return webp_filename, True
        except Exception as e:
            print(f"Error converting image to WebP: {e}")
    
    final_filename = f"{basename}{original_extension}"
    final_filepath = os.path.join(output_folder, final_filename)
    file_storage.seek(0)
    file_storage.save(final_filepath)
    return final_filename, False

# Cargar productos desde el archivo JSON
def load_products():
    try:
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # If the file doesn't exist on the persistent disk, create it with an empty list
        save_products([])
        return []

def save_products(products):
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, indent=4, ensure_ascii=False)

# Funciones para cargar y guardar categorías
def load_categories():
    try:
        with open(CATEGORIES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        save_categories([])
        return []

def save_categories(categories):
    with open(CATEGORIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(categories, f, indent=4, ensure_ascii=False)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)

@app.route('/')
def index():
    products = load_products()
    categories = load_categories()
    products_json = json.dumps(products)
    featured_products = sorted([p for p in products if 'views' in p], key=lambda x: x.get('views', 0), reverse=True)[:4]
    return render_template('index.html', products=products, categories=categories, products_json=products_json, featured_products=featured_products)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USER['username'] and password == ADMIN_USER['password']:
            user = User(username)
            login_user(user)
            return redirect(url_for('admin'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if request.method == 'POST':
        products = load_products()
        new_id = max([p['id'] for p in products]) + 1 if products else 1

        if 'image' not in request.files or request.files['image'].filename == '':
            flash('La imagen es obligatoria.')
            return redirect(request.url)
        
        file = request.files['image']
        basename = f"product_{new_id}"
        new_filename, converted = save_image(file, app.config['UPLOAD_FOLDER'], basename)

        if not converted:
            flash('El formato de la imagen no es compatible para la conversión a WebP. Se ha guardado la imagen original.', 'warning')

        image_url = url_for('uploaded_file', filename=new_filename)

        new_product = {
            "id": new_id,
            "name": request.form['name'],
            "description": request.form['description'],
            "price": float(request.form['price']),
            "image": image_url,
            "category_id": int(request.form['category_id']),
            "views": 0
        }
        products.append(new_product)
        save_products(products)
        flash('Producto agregado exitosamente!')
        return redirect(url_for('admin'))
    
    products = load_products()
    categories = load_categories()
    return render_template('admin.html', products=products, categories=categories)

@app.route('/admin/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    products = load_products()
    product_to_edit = next((p for p in products if p['id'] == product_id), None)
    if not product_to_edit:
        flash('Producto no encontrado.')
        return redirect(url_for('admin'))

    if request.method == 'POST':
        product_to_edit['name'] = request.form['name']
        product_to_edit['description'] = request.form['description']
        product_to_edit['price'] = float(request.form['price'])
        product_to_edit['category_id'] = int(request.form['category_id'])

        if 'image' in request.files and request.files['image'].filename != '':
            file = request.files['image']
            
            if 'image' in product_to_edit and product_to_edit.get('image'):
                try:
                    old_filename = os.path.basename(product_to_edit['image'])
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(old_filename)))
                except (FileNotFoundError, IndexError):
                    pass

            basename = f"product_{product_id}_{int(time.time())}"
            new_filename, converted = save_image(file, app.config['UPLOAD_FOLDER'], basename)

            if not converted:
                flash('El formato de la imagen no es compatible para la conversión a WebP. Se ha guardado la imagen original.', 'warning')
            
            product_to_edit['image'] = url_for('uploaded_file', filename=new_filename)

        save_products(products)
        flash('Producto actualizado exitosamente!')
        return redirect(url_for('admin'))
    categories = load_categories()
    return render_template('edit_product.html', product=product_to_edit, categories=categories)

@app.route('/admin/delete_product/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    products = load_products()
    product_to_delete = next((p for p in products if p['id'] == product_id), None)

    if product_to_delete and product_to_delete.get('image'):
        try:
            filename = os.path.basename(product_to_delete['image'])
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename)))
        except (FileNotFoundError, IndexError):
            pass # Ignore if file not found

    products = [p for p in products if p['id'] != product_id]
    save_products(products)
    flash('Producto eliminado exitosamente!')
    return redirect(url_for('admin'))

@app.route('/admin/categories', methods=['GET', 'POST'])
@login_required
def manage_categories():
    if request.method == 'POST':
        categories = load_categories()
        new_id = max([c['id'] for c in categories]) + 1 if categories else 1

        if 'image' not in request.files or request.files['image'].filename == '':
            flash('La imagen de la categoría es obligatoria.')
            return redirect(request.url)
        
        file = request.files['image']
        basename = f"category_{new_id}"
        new_filename, converted = save_image(file, app.config['UPLOAD_FOLDER'], basename)

        if not converted:
            flash('El formato de la imagen no es compatible para la conversión a WebP. Se ha guardado la imagen original.', 'warning')

        image_url = url_for('uploaded_file', filename=new_filename)

        new_category = {
            "id": new_id,
            "name": request.form['name'],
            "image": image_url
        }
        categories.append(new_category)
        save_categories(categories)
        flash('Categoría agregada exitosamente!')
        return redirect(url_for('manage_categories'))

    categories = load_categories()
    return render_template('categories.html', categories=categories)

@app.route('/admin/edit_category/<int:category_id>', methods=['GET', 'POST'])
@login_required
def edit_category(category_id):
    categories = load_categories()
    category_to_edit = next((c for c in categories if c['id'] == category_id), None)
    if not category_to_edit:
        flash('Categoría no encontrada.')
        return redirect(url_for('manage_categories'))

    if request.method == 'POST':
        category_to_edit['name'] = request.form['name']

        if 'image' in request.files and request.files['image'].filename != '':
            file = request.files['image']
            
            if 'image' in category_to_edit and category_to_edit.get('image'):
                try:
                    old_filename = os.path.basename(category_to_edit['image'])
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(old_filename)))
                except (FileNotFoundError, IndexError):
                    pass

            basename = f"category_{category_id}_{int(time.time())}"
            new_filename, converted = save_image(file, app.config['UPLOAD_FOLDER'], basename)

            if not converted:
                flash('El formato de la imagen no es compatible para la conversión a WebP. Se ha guardado la imagen original.', 'warning')

            category_to_edit['image'] = url_for('uploaded_file', filename=new_filename)

        save_categories(categories)
        flash('Categoría actualizada exitosamente!')
        return redirect(url_for('manage_categories'))

    return render_template('edit_category.html', category=category_to_edit)

@app.route('/admin/delete_category/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    categories = load_categories()
    products = load_products()
    category_to_delete = next((c for c in categories if c['id'] == category_id), None)

    if category_to_delete:
        if 'image' in category_to_delete and category_to_delete.get('image'):
            try:
                filename = os.path.basename(category_to_delete['image'])
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename)))
            except (FileNotFoundError, IndexError):
                pass
        
        categories = [c for c in categories if c['id'] != category_id]
        save_categories(categories)

        # Also delete products associated with this category
        products_to_keep = []
        products_deleted_count = 0
        for p in products:
            if p.get('category_id') == category_id:
                if p.get('image'):
                    try:
                        filename = os.path.basename(p['image'])
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename)))
                    except (FileNotFoundError, IndexError):
                        pass # Ignore if file not found
                products_deleted_count += 1
            else:
                products_to_keep.append(p)
        
        if products_deleted_count > 0:
            save_products(products_to_keep)

        flash(f'Categoría y {products_deleted_count} producto(s) asociado(s) eliminados exitosamente!')
    else:
        flash('Categoría no encontrada.', 'warning')
    return redirect(url_for('manage_categories'))

@app.route('/category/<int:category_id>')
def show_category(category_id):
    all_products = load_products()
    all_categories = load_categories()
    category = next((c for c in all_categories if c['id'] == category_id), None)
    products_in_category = [p for p in all_products if p.get('category_id') == category_id]
    products_json = json.dumps(all_products)
    
    return render_template('category_products.html', products=products_in_category, category=category, categories=all_categories, products_json=products_json)

@app.route('/product/<int:product_id>/view', methods=['POST'])
def record_view(product_id):
    products = load_products()
    product = next((p for p in products if p['id'] == product_id), None)
    if product:
        if 'views' not in product:
            product['views'] = 0
        product['views'] += 1
        save_products(products)
        return jsonify(success=True)
    return jsonify(success=False, error='Product not found'), 404

if __name__ == '__main__':
    app.run(debug=False)