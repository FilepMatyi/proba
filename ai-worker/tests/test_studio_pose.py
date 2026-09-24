import os
import sys
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.studio_compose import create_studio_image
from processing.studio_pose import (analyze_photo_pose, conservative_roll_correction,
                                    normalize_photo_pose, photo_placement)


def car_with_hitch():
    image = Image.new('RGBA', (600, 360))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 75, 540, 245), fill=(40, 105, 65, 255))
    draw.ellipse((95, 210, 195, 329), fill=(18, 20, 20, 255))
    draw.ellipse((390, 210, 500, 329), fill=(18, 20, 20, 255))
    draw.rectangle((544, 245, 550, 353), fill=(18, 20, 20, 255))
    return image


def tires(left_y=329., right_y=329.):
    return [{'x': 145., 'y': left_y, 'radius': 52., 'prominence': 34., 'confidence': .8},
            {'x': 445., 'y': right_y, 'radius': 54., 'prominence': 35., 'confidence': .8}]


class StudioPoseTests(unittest.TestCase):
    def test_roll_requires_agreeing_independent_evidence(self):
        self.assertAlmostEqual(conservative_roll_correction('side', 1.7, 1.4), 1.535)
        self.assertAlmostEqual(conservative_roll_correction('front-rear', -1.5, -1.0), -1.225)
        self.assertEqual(conservative_roll_correction('three-quarter', 20., 1.), 0.)
        self.assertEqual(conservative_roll_correction('side', -2.5, 1.5), 0.)
        self.assertEqual(conservative_roll_correction('front-rear', 1., None), 0.)
        self.assertLessEqual(abs(conservative_roll_correction('side', 4., 2.)), 2.)

    def test_tire_anchor_ignores_lower_hitch_and_places_contact_on_floor(self):
        image = car_with_hitch()
        with patch('processing.studio_pose.tire_contacts', return_value=tires()), \
             patch('processing.studio_pose._body_line_angles', return_value=[]):
            pose = analyze_photo_pose(image)
            composed, placed = create_studio_image(image, canvas_size=(800, 450),
                                                   style='photo', return_pose=True)
        self.assertEqual(composed.size, (800, 450))
        self.assertEqual(pose['groundAnchorSource'], 'tires')
        self.assertEqual(pose['groundAnchorY'], 329.)
        self.assertLess(pose['groundAnchorY'], 353.)  # Hitch bottom.
        self.assertAlmostEqual(placed['canvas']['contactY'][0], placed['canvas']['groundY'], delta=1.)
        self.assertAlmostEqual(placed['canvas']['contactY'][1], placed['canvas']['groundY'], delta=1.)

    def test_three_quarter_perspective_not_rotated_and_near_tire_anchors(self):
        image = car_with_hitch()
        perspective = tires(255., 329.)
        with patch('processing.studio_pose.tire_contacts', return_value=perspective), \
             patch('processing.studio_pose._body_line_angles', return_value=[(1., 130.), (1.2, 125.)]):
            normalized, pose = normalize_photo_pose(image)
        self.assertIs(normalized, image)
        self.assertEqual(pose['appliedRollDegrees'], 0.)
        self.assertEqual(pose['groundAnchorY'], 329.)
        self.assertGreater(abs(pose['wheelLineDegrees']), 10.)

    def test_small_supported_roll_is_applied_on_side_and_axial_views(self):
        image = car_with_hitch()
        for view in ('side', 'front-rear'):
            first = {'rollCorrectionDegrees': 1.25, 'wheelLineDegrees': 1.4}
            second = {'rollCorrectionDegrees': 0., 'wheelLineDegrees': .15}
            with self.subTest(view=view), patch('processing.studio_pose.analyze_photo_pose',
                                                side_effect=[first, second]):
                normalized, pose = normalize_photo_pose(image)
            self.assertGreater(normalized.width, image.width)
            self.assertAlmostEqual(pose['appliedRollDegrees'], 1.25)
            self.assertAlmostEqual(pose['wheelLineDegrees'], .15)

    def test_framing_and_vertical_stance_are_template_consistent(self):
        canvas = (3840, 2160)
        first = photo_placement((600, 360), 329., canvas)
        second = photo_placement((840, 490), 448., canvas)
        self.assertEqual(first[0][1], second[0][1])
        for dimensions, (x, y), ground_y in (first, second):
            self.assertEqual(x, (canvas[0]-dimensions[0])//2)
            self.assertEqual(ground_y, round(canvas[1]*.8722))
        self.assertAlmostEqual(first[1][1]+329*first[0][1]/360, first[2], delta=1.)
        self.assertAlmostEqual(second[1][1]+448*second[0][1]/490, second[2], delta=1.)

    def test_shadow_and_reflection_follow_final_photo_placement(self):
        image = car_with_hitch()
        with patch('processing.studio_pose.tire_contacts', return_value=tires()), \
             patch('processing.studio_pose._body_line_angles', return_value=[]), \
             patch('processing.studio_compose.photo_shadow_layers', wraps=None) as shadows, \
             patch('processing.studio_compose.floor_reflection',
                   return_value=Image.new('RGBA', (1, 1))) as reflection:
            _, pose = create_studio_image(image, canvas_size=(800, 450),
                                          style='photo', return_pose=True)
        args = shadows.call_args.args
        self.assertEqual(args[3], pose['canvas']['groundY'])
        self.assertEqual([round(item['canvasY'], 1) for item in args[4]], pose['canvas']['contactY'])
        self.assertEqual(reflection.call_args.args[1],
                         pose['canvas']['groundY']-pose['canvas']['y'])

    def test_empty_mask_is_safe(self):
        photo, pose = create_studio_image(Image.new('RGBA', (300, 180)),
                                          canvas_size=(800, 450), style='photo',
                                          return_pose=True)
        self.assertEqual(photo.size, (800, 450))
        self.assertIsNone(pose['groundAnchorY'])


if __name__ == '__main__':
    unittest.main()
