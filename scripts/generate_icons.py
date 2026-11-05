"""
Generate PWA icons for the e-FIR application
Creates icon-192.png and icon-512.png
"""
import os

try:
    from PIL import Image, ImageDraw, ImageFont
    
    def create_icon(size, output_path):
        """Create a simple icon with text."""
        # Create image with background color matching theme
        img = Image.new('RGB', (size, size), color='#1F3A2B')
        draw = ImageDraw.Draw(img)
        
        # Draw a shield-like shape
        margin = size // 8
        shield_points = [
            (size // 2, margin),  # top center
            (size - margin, margin + size // 4),  # top right
            (size - margin, size - margin - size // 8),  # bottom right
            (size // 2, size - margin),  # bottom center point
            (margin, size - margin - size // 8),  # bottom left
            (margin, margin + size // 4),  # top left
        ]
        draw.polygon(shield_points, fill='#F5EBE0', outline='#84A98C', width=max(2, size // 64))
        
        # Draw text
        try:
            # Try to use a system font
            font_size = size // 4
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        text = "e-FIR"
        # Get text size for centering
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Draw text in center
        text_x = (size - text_width) // 2
        text_y = (size - text_height) // 2 - size // 16
        draw.text((text_x, text_y), text, fill='#1F3A2B', font=font)
        
        # Save the image
        img.save(output_path, 'PNG')
        print(f"✅ Created {output_path} ({size}x{size})")
        return True
    
    # Create static directory if it doesn't exist
    static_dir = 'static'
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
        print(f"✅ Created {static_dir}/ directory")
    
    # Generate icons
    print("\n🎨 Generating PWA Icons...")
    print("=" * 60)
    
    success = True
    success = create_icon(192, os.path.join(static_dir, 'icon-192.png')) and success
    success = create_icon(512, os.path.join(static_dir, 'icon-512.png')) and success
    
    print("=" * 60)
    if success:
        print("✅ All icons generated successfully!")
        print("\nGenerated files:")
        print("  • static/icon-192.png (192x192)")
        print("  • static/icon-512.png (512x512)")
    else:
        print("❌ Some icons failed to generate")
    
except ImportError:
    print("=" * 60)
    print("⚠️  Pillow (PIL) not installed")
    print("=" * 60)
    print("\nTo generate icons, install Pillow:")
    print("  pip install Pillow")
    print("\nOr:")
    print("  python3 -m pip install Pillow")
    print("\nThen run:")
    print("  python3 generate_icons.py")
    print("=" * 60)
except Exception as e:
    print(f"❌ Error generating icons: {str(e)}")
    import traceback
    traceback.print_exc()
