# --- NEW CODE (Local MongoDB) ---
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import urllib.parse
import jwt 
from datetime import datetime, timedelta, timezone
from functools import wraps 
from flask_bcrypt import Bcrypt 
import uuid 


# ... (other imports)

# Remove urllib.parse import if no longer needed for other things

# --- Configuration & Initialization ---

# !!! IMPORTANT: Replace with a strong, secret key for JWT signing
SECRET_KEY = 'your_super_secret_jwt_key_here_please_change' 

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Enable CORS for all origins, allowing the React frontend to communicate
CORS(app)
bcrypt = Bcrypt(app) # Initialize Bcrypt

# ... (Logging Setup remains the same)

# --- MongoDB Connection Configuration (Local Setup) ---

# Set the URI for a local MongoDB instance running on the default port (27017)
# You can add user authentication details here if your local DB requires them.
MONGO_URI = "mongodb://localhost:27017/"
app.logger.info(f"MongoDB connection attempt using local URI: {MONGO_URI}")

# MongoDB connection
client = None
db = None
users_collection = None 
tenants_collection = None 
employees_collection = None # Renamed from students_collection
attendance_collection = None # NEW: For clock-in/out records

try:
    client = MongoClient(MONGO_URI)
    # Use a specific database name for your application
    db = client.get_database("Attendance_System_DB") 
    
    # Initialize Collections
    users_collection = db.users 
    tenants_collection = db.tenants 
    employees_collection = db.employees_info 
    attendance_collection = db.attendance_logs 
    
    client.admin.command('ping') 
    app.logger.info("Successfully connected to local MongoDB!") 
    print("Successfully connected to local MongoDB!")
    
except Exception as e:
    app.logger.error(f"FATAL ERROR: Failed to connect to MongoDB: {e}") 
    
# ... (The rest of your app.py code continues here)


# Upload configuration
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Authentication and Authorization Decorators ---

def token_required(f):
    """Decorator to check for a valid JWT token in the request headers."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

        if not token:
            app.logger.warning("Token missing in request header.")
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.current_user = data
            app.logger.info(f"User {data.get('username')} (Tenant {data.get('tenant_id')}) authenticated.")
        except jwt.ExpiredSignatureError:
            app.logger.warning("Expired token received.")
            return jsonify({'message': 'Token is expired!'}), 401
        except jwt.InvalidTokenError:
            app.logger.error("Invalid token received.")
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(*args, **kwargs)

    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Calls the existing token_required logic to verify the JWT
        result = token_required(f)(*args, **kwargs)
        
        # Check if token_required returned an error response
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
            return result
        
        # Now check for 'admin' role in the roles array
        if 'admin' not in request.current_user.get('roles', []):
            return jsonify({'message': 'Authorization failed: Admin privileges required'}), 403
            
        return f(*args, **kwargs)
    return decorated

def team_required(required_teams):
    """
    Decorator to check if the user belongs to any of the specified teams/roles.
    required_teams must be a list of strings (e.g., ['hr_team', 'finance_team'])
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. First, verify the JWT is valid (re-use token_required logic)
            # This is a common pattern to ensure the token is authenticated before checking specific roles
            result = token_required(f)(*args, **kwargs)
            
            # Check if token_required returned an error response
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
                return result
                
            user_roles = request.current_user.get('roles', [])
            
            # 2. Check for intersection: Does the user have any of the required teams?
            is_authorized = any(team in user_roles for team in required_teams)
            
            # 3. Admins are generally granted access to all team-required routes
            if 'admin' in user_roles:
                is_authorized = True

            if not is_authorized:
                return jsonify({'message': f'Authorization failed: Required teams ({", ".join(required_teams)}) access denied.'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

    
# --- Tenant and User Registration Routes ---

@app.route('/api/register_tenant', methods=['POST'])
def register_tenant():
    """
    Registers a new educational institution (tenant) and creates its initial administrator user.
    """
    if client is None or users_collection is None or tenants_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    
    required_fields = ['institution_name', 'admin_username', 'admin_password']
    if not all(field in data for field in required_fields):
        app.logger.warning(f"Tenant registration failed: Missing fields in request.")
        return jsonify({'message': 'Missing required fields: institution_name, admin_username, admin_password'}), 400

    institution_name = data['institution_name']
    admin_username = data['admin_username']
    admin_password = data['admin_password']

    new_tenant_id = str(uuid.uuid4().hex)[:6].upper()
    
    if tenants_collection.find_one({"name": institution_name}):
        app.logger.warning(f"Tenant registration conflict: Institution name '{institution_name}' already registered.")
        return jsonify({'message': f"Institution name '{institution_name}' is already registered."}), 409

    tenant_data = {
        "tenant_id": new_tenant_id,
        "name": institution_name,
        "date_registered": datetime.now(timezone.utc).isoformat()
    }

    hashed_password = bcrypt.generate_password_hash(admin_password).decode('utf-8')
    admin_user_data = {
        "username": admin_username,
        "password": hashed_password,
        "role": "admin",
        "tenant_id": new_tenant_id ,
        "employee_id":"A01",
        "is_active":True
    }

    try:
        if users_collection.find_one({"username": admin_username}):
            app.logger.warning(f"Admin username conflict during tenant registration: '{admin_username}' globally taken.")
            return jsonify({'message': f"Admin username '{admin_username}' is already taken."}), 409

        tenants_collection.insert_one(tenant_data)
        users_collection.insert_one(admin_user_data)
        app.logger.info(f"New Tenant '{institution_name}' registered with ID: {new_tenant_id}. Admin user '{admin_username}' created.")

        return jsonify({
            "message": f"Institution '{institution_name}' registered successfully.",
            "tenant_id": new_tenant_id,
            "admin_username": admin_username,
            "login_instructions": "Use this tenant_id along with the admin username and password to log in."
        }), 201

    except Exception as e:
        app.logger.error(f"Error during tenant registration for {institution_name}: {e}")
        return jsonify({"error": "Server error during registration. Please try again."}), 500  

# --- Login Route ---

@app.route('/api/login', methods=['POST'])
def login():
    """
    Handles user login. Issues a JWT containing role, tenant_id, AND employee_id.
    """
    if client is None or users_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    auth = request.get_json()

    if not auth or not auth.get('username') or not auth.get('password') or not auth.get('tenant_id'):
        return jsonify({'message': 'Missing username, password, or tenant_id'}), 400

    user = users_collection.find_one({
        'username': auth['username'],
        'tenant_id': auth['tenant_id']
    })

    if not user:
        return jsonify({'message': 'Login failed: Invalid credentials'}), 401
    
    if user["role"]=="user" :
        if user["is_active"]==False:
            return jsonify({'message': 'Login failed: Old Employee/User'}), 401


    if bcrypt.check_password_hash(user['password'], auth['password']):
        
        payload = {
            'username': user['username'],
            'role': user['role'],
            'tenant_id': user['tenant_id'], 
            'employee_id': user.get('employee_id'), # NEW: Include Employee ID in the token
            'exp': datetime.now(timezone.utc) + timedelta(hours=2),
            'iat': datetime.now(timezone.utc)
        }
        
        token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
        
        app.logger.info(f"User '{user['username']}' successfully logged in.")
        
        return jsonify({
            'username': user['username'],
            'token': token, 
            'role': user['role'], 
            'tenant_id': user['tenant_id'],
            'employee_id': user.get('employee_id') # Return it directly to the client
        }), 200

    return jsonify({'message': 'Login failed: Invalid credentials'}), 401

@app.route('/api/onboard_employee', methods=['POST'])
@team_required(['admin','hr_team'])
def onboard_employee():
    """
    Consolidated API to create both the Employee Profile and the linked User Login Account.
    This replaces separate calls to /api/employees and /api/add_user.
    """
    if client is None or employees_collection is None or users_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    tenant_id = request.current_user.get('tenant_id')

    # --- 1. Validate Required Fields ---
    
    # Fields required for both Employee Profile and User Login
    required_fields = ['employee_id', 'name', 'position', 'business_unit', 'username', 'password']
    if not all(field in data for field in required_fields):
        missing = [f for f in required_fields if f not in data]
        return jsonify({'message': f'Missing required fields: {", ".join(missing)}'}), 400

    employee_id = str(data['employee_id'])
    new_username = data['username']
    new_password = data['password']
    
    # Optional fields
    reports_to_ids = data.get('reports_to_employee_ids', []) 
    if isinstance(reports_to_ids, str): reports_to_ids = [reports_to_ids]
    new_role = data.get('role', 'user').lower()
    
    if new_role not in ['user', 'admin']:
          return jsonify({'message': "Invalid role specified. Must be 'user' or 'admin'."}), 400

    # --- 2. Conflict Checks ---

    # A. Check for employee ID conflict
    if employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id}):
        return jsonify({'message': f"Employee ID '{employee_id}' is already registered."}), 409 
    
    # B. Check for username conflict
    if users_collection.find_one({"username": new_username, "tenant_id": tenant_id}):
        return jsonify({'message': f"Username '{new_username}' is already taken."}), 409 

    # C. Check for manager existence (optional, but good practice)
    if reports_to_ids:
        approver_check = employees_collection.find({"employee_id": {"$in": reports_to_ids}, "tenant_id": tenant_id})
        found_approver_ids = [emp['employee_id'] for emp in approver_check]
        missing_ids = [id for id in reports_to_ids if id not in found_approver_ids]
        if missing_ids:
            return jsonify({'message': f"Manager IDs not found in this institution: {', '.join(missing_ids)}"}), 400

    # --- 3. Data Construction ---

    # Employee Profile Data
    new_employee_data = {
        "employee_id": employee_id,
        "tenant_id": tenant_id,
        "name": data['name'],
        "position": data['position'],
        "business_unit": data['business_unit'],
        "contact_email": data.get('contact_email', new_username), # Use username as fallback email
        "reports_to_employee_ids": reports_to_ids,
        "is_active": data.get('is_active', True),
        "date_added": datetime.now(timezone.utc).isoformat(),
        # "old_employee": False,
    }
    
    # User Login Data
    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    new_user_data = {
        "username": new_username,
        "password": hashed_password,
        "role": new_role,
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "is_active": True, # Login is active by default upon creation
        # "old_employee": False
    }

    # --- 4. Atomic Database Operation ---
    
    try:
        # Create Employee Profile
        employees_collection.insert_one(new_employee_data)
        
        # Create Linked User Login
        users_collection.insert_one(new_user_data)
        
        app.logger.info(f"Unified onboarding successful for Employee {employee_id} ({new_username}).")
        
        return jsonify({
            "message": f"Employee '{data['name']}' and linked User Login created successfully.",
            "employee_id": employee_id,
            "tenant_id": tenant_id,
            "username": new_username,
            "role": new_role
        }), 201

    except Exception as e:
        # If one insert fails after the first, you might need rollback logic here.
        # For MongoDB, the simplest rollback is to try and clean up what was successfully inserted.
        employees_collection.delete_one({"employee_id": employee_id, "tenant_id": tenant_id})
        users_collection.delete_one({"username": new_username, "tenant_id": tenant_id})
        
        app.logger.error(f"Error during unified onboarding for {employee_id}. Attempted rollback: {e}")
        return jsonify({"error": "Server error during onboarding. Transaction failed and rolled back."}), 500

@app.route('/api/employees', methods=['GET'])
@admin_required
def get_all_employees():
    """
    Retrieves a list of all employees belonging to the admin's tenant.
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    
    try:
        # Find all employees for the current tenant
        employee_list = list(employees_collection.find({"tenant_id": tenant_id}, {'_id': 0}))
        
        # NOTE: Consider pagination for large numbers of employees in a real-world app.
        
        app.logger.info(f"Retrieved {len(employee_list)} employees for tenant {tenant_id}.")
        return jsonify(employee_list), 200
    except Exception as e:
        app.logger.error(f"Error retrieving employees for tenant {tenant_id}: {e}")
        return jsonify({"error": "Server error retrieving employee list."}), 500

@app.route('/api/employee/<employee_id>', methods=['GET'])
@admin_required
def get_single_employee(employee_id):
    """
    Retrieves details for a single employee by their ID within the tenant.
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    
    try:
        employee = employees_collection.find_one({
            "employee_id": employee_id,
            "tenant_id": tenant_id
        }, {'_id': 0})

        if employee:
            app.logger.info(f"Retrieved details for employee ID {employee_id} in tenant {tenant_id}.")
            return jsonify(employee), 200
        else:
            app.logger.warning(f"Employee ID {employee_id} not found in tenant {tenant_id}.")
            return jsonify({"message": f"Employee ID {employee_id} not found in this institution."}), 404
    except Exception as e:
        app.logger.error(f"Error retrieving employee {employee_id} for tenant {tenant_id}: {e}")
        return jsonify({"error": "Server error retrieving employee details."}), 500 

@app.route('/api/employee/<employee_id>', methods=['PUT'])
@admin_required
def update_employee(employee_id):
    """
    Allows an admin to update an employee's details (e.g., position, business_unit, reports_to, or status).
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    update_data = request.get_json()
    
    # 1. Validation for the employee's existence
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        return jsonify({"message": f"Employee ID {employee_id} not found."}), 404
        
    # --- Special Handling for Offboarding ---
    # If the request includes is_active=False, we can trigger offboarding actions
    if 'is_active' in update_data and update_data['is_active'] == False:
        # A. Disable Login Account (Crucial for security)
        users_collection.update_one(
            {"employee_id": employee_id, "tenant_id": tenant_id},
            {"$set": {"is_active": False, "status_note": "Terminated/Inactive"}}
        )
        app.logger.info(f"User login disabled for employee {employee_id} in tenant {tenant_id}.")
        
        # B. Clean up open attendance session
        # Find and clock-out any open session for the employee (prevents phantom work hours)
        attendance_collection.update_one(
            {"employee_id": employee_id, "tenant_id": tenant_id, "clock_out_time": {"$exists": False}},
            {"$set": {"clock_out_time": datetime.now(timezone.utc).isoformat(), "status": "OUT (System Offboard)"}}
        )
        
    # --- General Data Update ---
    
    # Clean up the payload to avoid trying to overwrite immutable fields
    update_data.pop('employee_id', None)
    update_data.pop('tenant_id', None)

    try:
        employees_collection.update_one(
            {"_id": employee['_id']},
            {"$set": update_data}
        )
        app.logger.info(f"Employee {employee_id} updated successfully.")
        return jsonify({"message": f"Employee {employee_id} data and status updated successfully."}), 200

    except Exception as e:
        app.logger.error(f"Error updating employee {employee_id}: {e}")
        return jsonify({"error": "Server error during employee update."}), 500

@app.route('/api/employee/<employee_id>', methods=['DELETE'])
@admin_required
def delete_employee(employee_id):
    """
    Allows an admin to completely delete an employee and all related data (user login, attendance, leave requests).
    This action is irreversible and should be used with caution.
    """
    # if client is None or employees_collection is None or users_collection is None or attendance_collection is None or leave_requests_collection is None:
    if client is None or employees_collection is None or users_collection is None or attendance_collection is None :    
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    
    # 1. Validation for the employee's existence
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        app.logger.warning(f"Deletion failed: Employee ID {employee_id} not found in tenant {tenant_id}.")
        return jsonify({"message": f"Employee ID {employee_id} not found."}), 404

    try:
        # --- CASCADE CLEANUP OPERATIONS ---
        
        # A. Disable/Delete Login Account
        # We will delete the login account linked to this employee_id
        users_result = users_collection.delete_many({"employee_id": employee_id, "tenant_id": tenant_id})
        
        # B. Clean up Attendance Logs (Optional: DELETE vs. Anonymize/Retain)
        # Choosing to delete the logs for a clean removal.
        attendance_result = attendance_collection.delete_many({"employee_id": employee_id, "tenant_id": tenant_id})

        # C. Clean up Leave Requests (as the person making the request)
        # Delete all pending/historical leave requests made by this employee
        leave_req_result = leave_requests_collection.delete_many({"employee_id": employee_id, "tenant_id": tenant_id})

        # D. Clean up Leave Approvals (as a manager)
        # Remove the departing employee from any pending requests where they were an approver.
        # This prevents requests from being stuck if they were the only approver.
        leave_requests_collection.update_many(
            {"tenant_id": tenant_id, "approvals_needed.approver_id": employee_id, "status": "Pending"},
            {
                "$pull": {"approvals_needed": {"approver_id": employee_id}}
            }
        )
        # If any request is now left with zero approvers needed, the admin should manually review/finalize it.
        
        # E. Delete the main Employee Profile
        employee_result = employees_collection.delete_one({"_id": employee['_id']})
        
        # --- Log and Response ---
        
        app.logger.info(f"Employee {employee_id} ({employee['name']}) and associated records fully deleted by admin {request.current_user.get('username')} in tenant {tenant_id}.")
        
        return jsonify({
            "message": f"Employee {employee_id} ({employee['name']}) successfully deleted.",
            "records_deleted": {
                "user_accounts": users_result.deleted_count,
                "employee_profiles": employee_result.deleted_count,
                "attendance_logs": attendance_result.deleted_count,
                "leave_requests_submitted": leave_req_result.deleted_count,
            },
            "next_step_required": "Manually run /api/hierarchy/reassign to update the direct reports of this deleted employee."
        }), 200

    except Exception as e:
        app.logger.error(f"FATAL ERROR during employee deletion for {employee_id}: {e}")
        return jsonify({"error": "Server error during cascade deletion."}), 500        

@app.route('/api/hierarchy/reassign', methods=['POST'])
@admin_required
def reassign_hierarchy():
    """
    Reassigns all employees who reported to an 'old_manager_id' to a 'new_manager_id'.
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    tenant_id = request.current_user.get('tenant_id')

    required_fields = ['old_manager_id', 'new_manager_id']
    if not all(field in data for field in required_fields):
        return jsonify({'message': 'Missing required fields: old_manager_id, new_manager_id'}), 400

    old_id = str(data['old_manager_id'])
    new_id = str(data['new_manager_id'])
    
    # 1. Validation: Ensure the new manager exists
    if not employees_collection.find_one({"employee_id": new_id, "tenant_id": tenant_id}):
        return jsonify({"message": f"New Manager ID {new_id} not found."}), 404

    # 2. Query to find all employees reporting to the old manager
    # We use $in to search within the array and $ne to ensure the old manager isn't the new manager
    query = {
        "tenant_id": tenant_id,
        "reports_to_employee_ids": old_id,
        "employee_id": {"$ne": new_id} # Exclude the new manager from reporting to themselves
    }
    
    # 3. Update Operation (Atomic update for all matching documents)
    try:
        # $pull removes the old_manager_id from the array
        employees_collection.update_many(
            query, 
            {"$pull": {"reports_to_employee_ids": old_id}}
        )
        
        # $addToSet adds the new_manager_id, ensuring no duplicates
        result = employees_collection.update_many(
            query,
            {"$addToSet": {"reports_to_employee_ids": new_id}}
        )
        
        count = result.modified_count
        app.logger.info(f"Reassigned {count} employees from {old_id} to {new_id}.")

        return jsonify({
            "message": f"Successfully reassigned hierarchy for {count} employees.",
            "employees_modified": count,
            "old_manager_id": old_id,
            "new_manager_id": new_id
        }), 200

    except Exception as e:
        app.logger.error(f"Error during hierarchy reassignment: {e}")
        return jsonify({"error": "Server error during hierarchy reassignment."}), 500        

# --- Attendance Tracking Routes (Clock In/Out) ---

from bson import ObjectId

@app.route('/api/clock_in', methods=['POST'])
@token_required 
def clock_in():
    if client is None or employees_collection is None or attendance_collection is None:
        return jsonify({"error": "Database connection not established."}), 500
    
    data = request.get_json()
    lat = data.get('latitude')
    lng = data.get('longitude')
    
    employee_id = request.current_user.get('employee_id')
    tenant_id = request.current_user.get('tenant_id')
    
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime('%Y-%m-%d')

    # 1. Look for existing open session
    open_session = attendance_collection.find_one({
        "employee_id": employee_id, 
        "tenant_id": tenant_id,
        "clock_out_time": {"$exists": False} 
    }, sort=[('clock_in_time', -1)])

    if open_session:
        # If they have an open session from a previous day, block them
        if open_session.get('clock_in_date') != today_str:
            return jsonify({
                "message": f"Clock-in blocked. You forgot to clock out on {open_session['clock_in_date']}.",
                "error_code": "MISSING_CLOCK_OUT",
                "pending_date": open_session['clock_in_date'],
                "attendance_id": str(open_session['_id']) # Include ID so they can force close it
            }), 403 
        
        # If already clocked in today, return the existing ID so the app can resume tracking
        return jsonify({
            "message": "You are already clocked in for today.",
            "attendance_id": str(open_session['_id'])
        }), 200

    # 2. Get Employee Profile
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    unit = employee.get('business_unit', 'Unassigned') if employee else 'Unassigned'

    # 3. Create the Clock-In Record
    log_data = {
        "employee_id": employee_id,
        "tenant_id": tenant_id,
        "business_unit": unit,
        "clock_in_date": today_str,
        "clock_in_time": now_utc.isoformat(),
        "status": "IN",
        "location_in": {
            "type": "Point",
            "coordinates": [lng, lat] 
        } if lat is not None and lng is not None else None
    }
    
    try:
        # 4. CAPTURE THE ID: result.inserted_id is critical for tracking
        result = attendance_collection.insert_one(log_data)
        attendance_id = str(result.inserted_id)

        return jsonify({
            "employee_id": employee_id,
            "tenant_id": tenant_id,
            "attendance_id": attendance_id, # <--- NEW: App needs this for /api/tracking/ping
            "message": "Clock-in successful.",
            "date": today_str,
            "time": now_utc.isoformat()
        }), 201
    except Exception as e:
        app.logger.error(f"Error during clock-in: {e}")
        return jsonify({"error": "Server error during clock-in."}), 500

@app.route('/api/clock_out', methods=['POST'])
@token_required 
def clock_out():
    if client is None or employees_collection is None or attendance_collection is None:
        return jsonify({"error": "Database connection not established."}), 500
    
    data = request.get_json()
    lat = data.get('latitude')
    lng = data.get('longitude')
    # NEW: The app should pass the attendance_id to ensure we close the right session
    attendance_id = data.get('attendance_id') 
    
    employee_id = request.current_user.get('employee_id')
    tenant_id = request.current_user.get('tenant_id')

    # 1. Verify Employee exists
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        return jsonify({'message': 'Invalid Employee ID'}), 404

    # 2. Target the specific record (Prefer using attendance_id if provided)
    if attendance_id:
        query = {"_id": ObjectId(attendance_id), "tenant_id": tenant_id}
    else:
        # Fallback to finding the open session if ID is missing
        query = {"employee_id": employee_id, "tenant_id": tenant_id, "clock_out_time": {"$exists": False}}

    latest_in_log = attendance_collection.find_one(query, sort=[('clock_in_time', -1)])
    
    if not latest_in_log:
        return jsonify({'message': 'Active session not found.'}), 404

    now_utc = datetime.now(timezone.utc)
    
    try:
        # 3. Update the record
        attendance_collection.update_one(
            {"_id": latest_in_log['_id']},
            {"$set": {
                "clock_out_date": now_utc.strftime('%Y-%m-%d'),
                "clock_out_time": now_utc.isoformat(),
                "status": "OUT",
                "location_out": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                } if lat is not None and lng is not None else None
            }}
        )
        
        # 4. Calculate duration
        clock_in_time = datetime.fromisoformat(latest_in_log['clock_in_time'].replace('Z', '+00:00'))
        duration = now_utc - clock_in_time
        total_seconds = int(duration.total_seconds())
        hours, minutes = total_seconds // 3600, (total_seconds % 3600) // 60

        return jsonify({
            "employee_id": employee_id,
            "attendance_id": str(latest_in_log['_id']),
            "message": f"Clocked out successfully.",
            "duration": f"{hours} hours and {minutes} minutes",
            "status": "OUT"
        }), 200
    except Exception as e:
        app.logger.error(f"Error during clock-out: {e}")
        return jsonify({"error": "Server error during clock-out."}), 500

@app.route('/api/attendance/adjust', methods=['POST'])
@team_required(['hr_team','admin']) # Only HR Approvers or Admins can fix logs
def adjust_attendance():
    """
    Allows HR to manually set a clock-out time for a forgotten session.
    """
    if client is None or attendance_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    record_id = data.get('record_id') # The MongoDB _id or a unique request ID
    manual_out_time = data.get('clock_out_time') # e.g., "2026-01-01T17:00:00"
    reason = data.get('reason')

    if not record_id or not manual_out_time:
        return jsonify({'message': 'Missing record_id or new clock_out_time'}), 400

    try:
        # Update the record with the manual time and a flag
        attendance_collection.update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {
                "clock_out_time": manual_out_time,
                "clock_out_date": manual_out_time.split('T')[0],
                "status": "MANUALLY_FIXED",
                "adjustment_note": reason,
                "adjusted_by": request.current_user['username']
            }}
        )
        
        return jsonify({"message": "Attendance record adjusted successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500        

# Leave application part


@app.route('/api/leave/request', methods=['POST'])
@token_required
def submit_leave_request():
    if client is None or employees_collection is None or leave_requests_collection is None:
        return jsonify({"error": "Database connection not established."}), 500
        
    data = request.get_json()
    tenant_id = request.current_user.get('tenant_id')
    # Use ID from token instead of body for security
    employee_id = request.current_user.get('employee_id') 
    
    employee_info = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee_info:
        return jsonify({'message': 'Employee profile not found.'}), 404
        
    # Get the list of managers
    approver_ids = employee_info.get('reports_to_employee_ids', [])
    if not approver_ids:
        return jsonify({'message': 'No managers assigned. Please contact HR.'}), 400

    required_fields = ['leave_type', 'start_date', 'end_date', 'reason']
    if not all(field in data for field in required_fields):
        return jsonify({'message': 'Missing leave details (type, dates, or reason).'}), 400
        
    try:
        # Fetch manager names to make the request readable
        approver_details = employees_collection.find(
            {"employee_id": {"$in": approver_ids}}, 
            {"employee_id": 1, "name": 1}
        )
        approver_map = {det['employee_id']: det['name'] for det in approver_details}

        # Build the multi-step approval array
        approvals_needed = []
        for a_id in approver_ids:
            approvals_needed.append({
                "approver_id": a_id,
                "name": approver_map.get(a_id, "Manager"),
                "status": "Pending",
                "decision_date": None
            })

        request_data = {
            "request_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "employee_id": employee_id,
            "employee_name": employee_info['name'],
            "business_unit": employee_info.get('business_unit', 'Unassigned'),
            "leave_type": data['leave_type'],
            "start_date": data['start_date'],
            "end_date": data['end_date'],
            "reason": data['reason'],
            "status": "Pending",
            "approvals_needed": approvals_needed,
            "requested_on": datetime.now(timezone.utc).isoformat()
        }
        
        leave_requests_collection.insert_one(request_data)
        return jsonify({"message": "Leave request submitted for manager approval.", "request_id": request_data['request_id']}), 201

    except Exception as e:
        app.logger.error(f"Leave submission error: {e}")
        return jsonify({"error": "Server error during leave submission."}), 500

@app.route('/api/leave/pending', methods=['GET'])
@token_required
def get_pending_leave_requests():
    if client is None or leave_requests_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    user_roles = request.current_user.get('roles', [])
    current_emp_id = request.current_user.get('employee_id')

    # Base query: only pending requests for this tenant
    query = {"tenant_id": tenant_id, "status": "Pending"}
    
    # Permission Logic
    is_hr_or_admin = any(role in ['admin', 'hr_manager'] for role in user_roles)

    if not is_hr_or_admin:
        # If not HR/Admin, show only where current user is a pending approver
        query["approvals_needed"] = {
            "$elemMatch": {
                "approver_id": current_emp_id,
                "status": "Pending"
            }
        }
    
    try:
        pending_requests = list(leave_requests_collection.find(query, {'_id': 0}).sort('requested_on', 1))
        return jsonify(pending_requests), 200
        
    except Exception as e:
        app.logger.error(f"Error retrieving pending requests: {e}")
        return jsonify({"error": "Server error."}), 500

@app.route('/api/leave/approve', methods=['POST'])
@token_required
def approve_leave_request():
    """
    Records a manager's decision for a leave request. 
    Finalizes the overall status if all required managers have signed off.
    """
    if client is None or leave_requests_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    request_id = data.get('request_id')
    decision = data.get('decision') # Expecting "Approved" or "Rejected"
    
    # Get Manager's identity from JWT
    current_emp_id = request.current_user.get('employee_id')
    user_roles = request.current_user.get('roles', [])
    now_str = datetime.now(timezone.utc).isoformat()

    if not request_id or not decision:
        return jsonify({"message": "Missing request_id or decision."}), 400

    # 1. Authorization: check if user is HR or Admin (Super-approver rights)
    is_hr_or_admin = any(role in ['admin', 'hr_team'] for role in user_roles)

    try:
        # 2. Update the specific manager's entry in the approvals_needed array
        # We find the request where this specific user is an approver
        result = leave_requests_collection.update_one(
            {
                "request_id": request_id,
                "approvals_needed.approver_id": current_emp_id
            },
            {
                "$set": {
                    "approvals_needed.$[elem].status": decision,
                    "approvals_needed.$[elem].decision_date": now_str
                }
            },
            array_filters=[{"elem.approver_id": current_emp_id}]
        )

        # If no document was updated, this user isn't a listed manager for this request
        if result.matched_count == 0 and not is_hr_or_admin:
            return jsonify({"message": "Forbidden: You are not an authorized approver for this request."}), 403

        # 3. Handle Overall Status
        updated_req = leave_requests_collection.find_one({"request_id": request_id})
        
        # Scenario A: If ANY manager rejects, the whole request is Rejected immediately
        if decision == "Rejected":
            leave_requests_collection.update_one(
                {"request_id": request_id},
                {"$set": {"status": "Rejected"}}
            )
            return jsonify({"message": "Leave request has been Rejected."}), 200

        # Scenario B: Check if EVERY manager in the array has now set status to "Approved"
        all_approved = all(a['status'] == "Approved" for a in updated_req['approvals_needed'])
        
        if all_approved:
            leave_requests_collection.update_one(
                {"request_id": request_id},
                {"$set": {"status": "Approved"}}
            )
            return jsonify({"message": "Final approval granted. Leave is now fully Approved."}), 200
        
        # Scenario C: Still waiting on other managers
        return jsonify({"message": f"Step approved. Waiting for remaining managers."}), 200

    except Exception as e:
        app.logger.error(f"Error in leave approval: {e}")
        return jsonify({"error": "Server error during approval process."}), 500       

@app.route('/api/tracking/ping', methods=['POST'])
@token_required
def location_ping():
    """
    Receives periodic GPS coordinates while the user is clocked in.
    """
    if client is None or db is None:
        app.logger.critical("Database connection lost during tracking ping!")
        return jsonify({"error": "Database connection not established."}), 500

    try:
        data = request.get_json()
        lat = data.get('latitude')
        lng = data.get('longitude')
        
        employee_id = request.current_user.get('employee_id')
        tenant_id = request.current_user.get('tenant_id')

        # Validation: Check if coordinates are present
        if lat is None or lng is None:
            app.logger.warning(f"Empty ping received from Employee {employee_id}")
            return jsonify({"message": "Coordinates missing."}), 400

        # 1. Verify the employee is currently Clocked IN
        active_session = attendance_collection.find_one({
            "employee_id": employee_id,
            "tenant_id": tenant_id,
            "clock_out_time": {"$exists": False}
        })

        if not active_session:
            app.logger.info(f"Ping rejected: Employee {employee_id} is not clocked in.")
            return jsonify({"message": "Tracking stopped: No active clock-in session."}), 403

        # 2. Record the movement ping
        ping_data = {
            "attendance_id": active_session['_id'],
            "employee_id": employee_id,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "location": {
                "type": "Point",
                "coordinates": [lng, lat]
            }
        }

        db.location_pings.insert_one(ping_data)
        return jsonify({"status": "Ping recorded"}), 200

    except Exception as e:
        app.logger.error(f"Unexpected error in /api/tracking/ping: {str(e)}")
        return jsonify({"error": "Internal server error while processing ping."}), 500


@app.route('/api/tracking/route/<attendance_id>', methods=['GET'])
@token_required
@team_required(['admin', 'hr_team', 'manager']) 
def get_shift_route(attendance_id):
    if client is None or db is None:
        app.logger.critical("Database connection failure in get_shift_route")
        return jsonify({"error": "Database connection not established."}), 500

    current_emp_id = request.current_user.get('employee_id')
    user_roles = request.current_user.get('role',[])
    print("current_emp_id",current_emp_id)
    print(user_roles)

    try:
        # 1. Fetch the shift record
        try:
            shift = attendance_collection.find_one({"_id": ObjectId(attendance_id)})
        except Exception:
            return jsonify({"message": "Invalid ID format"}), 400

        if not shift:
            return jsonify({"message": "Shift not found"}), 404

        # 2. THE LOGIC CHECK
        # Gate A: Is the user HR or Admin? (They get a "Pass")
        # is_hr_or_admin = any(role in ['admin', 'hr_team'] for role in user_roles)
        
        # Gate B: If NOT HR/Admin, check if they are the SPECIFIC manager
        if  user_roles=="admin":
            target_emp = employees_collection.find_one(
                {"employee_id": shift['employee_id'], "tenant_id": shift['tenant_id']}
            )
            
            # # Check the matrix reporting array
            # managers_list = target_emp.get('reports_to_employee_ids', [])
            
            # if current_emp_id not in managers_list:
            #     app.logger.warning(f"Unauthorized tracking attempt: {current_emp_id} tried to view {shift['employee_id']}")
            #     return jsonify({"message": "Access Denied: You do not manage this employee."}), 403

        # 3. Fetch Pings and Construct Path
        pings = list(db.location_pings.find({"attendance_id": ObjectId(attendance_id)}).sort("timestamp", 1))

        path = []
        # Start
        path.append({
            "time": shift['clock_in_time'], 
            "lat": shift['location_in']['coordinates'][1], 
            "lng": shift['location_in']['coordinates'][0], 
            "type": "START"
        })
        
        # Intermediate
        for p in pings:
            path.append({
                "time": p['timestamp'], 
                "lat": p['location']['coordinates'][1], 
                "lng": p['location']['coordinates'][0], 
                "type": "PING"
            })
        
        # End
        if shift.get('clock_out_time'):
            path.append({
                "time": shift['clock_out_time'], 
                "lat": shift['location_out']['coordinates'][1], 
                "lng": shift['location_out']['coordinates'][0], 
                "type": "END"
            })

        return jsonify({"attendance_id": attendance_id, "route": path}), 200

    except Exception as e:
        app.logger.error(f"Critical error in /api/tracking/route: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


