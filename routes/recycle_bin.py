from flask import render_template, request, jsonify, abort
from routes import recycle_bin_bp
from services.recycle_bin_service import RecycleBinService, RecycleBinRegistry
from services.auth_service import AuthService
from core.auth.permissions import can_manage_backups
from core.exceptions import BusinessException
from utils.pagination import get_pagination_params

@recycle_bin_bp.before_request
def _require_recycle_bin_permission():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    if not can_manage_backups(current_user):
        abort(403)

@recycle_bin_bp.route('/recycle-bin')
def index():
    """Display all soft-deleted records in the Recycle Bin with filters."""
    q = request.args.get('q', '').strip()
    item_type = request.args.get('item_type', '').strip()
    sort_by = request.args.get('sort_by', 'newest_deleted').strip()
    
    page, per_page = get_pagination_params()
        
    pagination = RecycleBinService.get_deleted_items(
        query=q,
        item_type=item_type,
        sort_by=sort_by,
        page=page,
        per_page=per_page
    )
    
    stats = RecycleBinService.get_statistics()
    
    return render_template(
        'recycle_bin/index.html',
        items=pagination,
        q=q,
        item_type=item_type,
        sort_by=sort_by,
        per_page=per_page,
        stats=stats
    )

@recycle_bin_bp.route('/recycle-bin/restore/<string:item_type>/<int:item_id>', methods=['POST'])
def restore(item_type, item_id):
    """Restore a soft-deleted item back to active status generically."""
    try:
        config = RecycleBinRegistry.get(item_type)
        if not config:
            return jsonify({'success': False, 'message': 'Loại dữ liệu không hợp lệ.'}), 400
            
        success = config['restore_func'](item_id, actor=AuthService.require_current_username())
        if success:
            return jsonify({'success': True, 'message': 'Khôi phục thành công.'})
        else:
            return jsonify({'success': False, 'message': 'Không thể khôi phục dữ liệu.'}), 400
    except BusinessException as be:
        return jsonify({'success': False, 'message': be.message}), be.status_code
    except ValueError as ve:
        # ValueError contains the validation error message from service
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception:
        return jsonify({'success': False, 'message': 'Không thể khôi phục dữ liệu.'}), 500

@recycle_bin_bp.route('/recycle-bin/delete/<string:item_type>/<int:item_id>', methods=['POST'])
def permanent_delete(item_type, item_id):
    """Permanently delete one approved soft-deleted business record."""
    try:
        result = RecycleBinService.permanent_delete(
            item_type,
            item_id,
            actor=AuthService.require_current_username(),
        )
        return jsonify({
            'success': True,
            'message': 'Đã xóa vĩnh viễn bản ghi.',
            'item_type': result['item_type'],
            'item_id': result['item_id'],
        })
    except BusinessException as be:
        return jsonify({'success': False, 'message': be.message}), be.status_code
    except Exception:
        return jsonify({'success': False, 'message': 'Không thể xóa vĩnh viễn bản ghi.'}), 500

@recycle_bin_bp.route('/recycle-bin/info/<string:item_type>/<int:item_id>', methods=['GET'])
def get_info(item_type, item_id):
    """Retrieve details and dependent counts of a soft-deleted item before permanent deletion."""
    try:
        config = RecycleBinRegistry.get(item_type)
        if not config:
            return jsonify({'success': False, 'message': 'Loại dữ liệu không hợp lệ.'}), 400
            
        info = config['info_func'](item_id)
        return jsonify({'success': True, 'info': info})
    except Exception:
        return jsonify({'success': False, 'message': 'Không thể lấy thông tin dữ liệu.'}), 500
