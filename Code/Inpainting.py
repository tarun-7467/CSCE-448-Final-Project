import cv2
import numpy as np
import math
import os
import errno

SOURCE_FOLDER = "../Images/"
OUT_FOLDER = "../Results/"


def boundary(img, x, y, window):
    # Ensure x, y, and window are scalars/integers
    if isinstance(x, np.ndarray) or isinstance(y, np.ndarray):
        raise ValueError("x and y must be scalar integers")
    if not isinstance(window, tuple):
        raise ValueError("window must be a tuple of two integers")

    #print(f"x: {x}, y: {y}, window: {window}")  # Debugging output

    img_width, img_height = img.shape[:2]
    x_left = max(x - window[0] // 2, 0) if (x - window[0] // 2) > 0 else x
    x_right = min(x + window[0] // 2, img_width - 1) if (x + window[0] // 2) < img_width else x
    y_top = max(y - window[1] // 2, 0) if (y - window[1] // 2) > 0 else y
    y_bottom = min(y + window[1] // 2, img_height - 1) if (y + window[1] // 2) < img_height else y 
    
    return x_left, x_right, y_top, y_bottom


def compute_norm(matrix):
    matrix = matrix ** 2
    return np.sqrt(np.sum(matrix))


def compute_priority(img, fill_front, mask, window):
    conf = compute_confidence(fill_front, window, mask, img)

    sobel_map = cv2.Sobel(src=mask.astype(float), ddepth=cv2.CV_64F, dx=1, dy=1, ksize=1)
    sobel_map_norm = compute_norm(sobel_map)
    sobel_map /= sobel_map_norm

    return fill_front * conf * sobel_map, conf


def invert(mask):
    return 1-mask

def compute_confidence(contours, window, mask, img):

    confidence = invert(mask).astype(np.float64)
        
    for i in range(len(contours)):
        for j in range(len(contours[0])):
            if contours[i][j] != 1:
                continue
            x_left, x_right, y_top, y_bottom = boundary(img, j, i, window)
            sumPsi = np.sum(confidence[y_top:y_bottom + 1 , x_left:x_right + 1])
            magPsi = (x_right - x_left) * (y_bottom - y_top)
            if magPsi > 0:
                confidence[i, j] = sumPsi / magPsi

    return confidence
        
def find_best_match(img, mask, window, priorityCoord):
    best_ssd = float('inf')
    best_match = []
    inverted_mask = invert(mask)

    x_coord = int(priorityCoord[0])
    y_coord = int(priorityCoord[1])

    print(f"({x_coord},{y_coord})")
    xl, xr, yt, yb = boundary(img, x_coord, y_coord, window)
    # xl, xr, yt, yb = boundary(img, priorityCoord[0], priorityCoord[1], patch_size)
    if xl is None:
        return None
    
    # target_patch = inverted_mask[yt:yb + 1, xl:xr + 1]
    target_patch = mask[yt:yb + 1, xl:xr + 1]
    if target_patch.size == 0:
        return None
    
    target_img = img[yt:yb + 1, xl:xr + 1] * target_patch

    for y in range(img.shape[1] - 1): 
        for x in range(img.shape[0] - 1):
            x_left, x_right, y_top, y_bottom = boundary(img, x, y, window)
            maskPatch = inverted_mask[y_top:y_bottom + 1, x_left: x_right + 1]

            if np.any(maskPatch == 0):
                continue
            print(f"{x},{y}")
            print(img[y_top:y_bottom + 1, x_left:x_right + 1].shape)
            print(target_patch.shape)
            print(f"{x_left},{x_right},{y_top},{y_bottom}")
            candidatePatch = img[y_top:y_bottom + 1, x_left:x_right + 1] * target_patch
    
            difference = np.linalg.norm(target_img - candidatePatch)
            if difference < best_ssd:
                best_ssd = difference
                best_match = [x_left, x_right, y_top, y_bottom]
                
    return best_match

# remix
def compute_fill_front(mask):
    if mask.shape[-1] == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    fill_front = np.zeros_like(mask)
    contours, _ = cv2.findContours(mask, mode=cv2.RETR_EXTERNAL, method=cv2.CHAIN_APPROX_SIMPLE)
    fill_front = cv2.drawContours(fill_front, contours, -1, (255, 255, 255), thickness=1) / 255.
    return fill_front.astype('uint8')


def update_Mask_Image(image, mask, bestRegion, updateRegion, updateRegionIndex, targetMask, windowSize):
    '''
    need the image, mask, best matching region from find best match
    update region is the region we want to update
    updateRegionIndex are the index points. this can be combined with the ones aove
    targetMask is the mask where inside the mask is 1 and outside of 0
    source mask is just the inverse of the
    '''
    invertedMask = 1 - targetMask
    lowX, highX, lowY, highY = bestRegion[0], bestRegion[1], bestRegion[2], bestRegion[3]
    sourceImageCopy = image[lowX:highX+1, lowY:highY+1] #the part of the image we want to duplicate into the target image
    newRegion = sourceImageCopy * targetMask #tarrget mask is just the regular mask inside of the box we want to fill
    oldRegion = invertedMask * updateRegion
    lowerXFill, upperXFill, lowerYFill, upperYFill = updateRegionIndex[0][0], updateRegionIndex[0][1], updateRegionIndex[1][0], updateRegionIndex[1][1]
   
    mask[lowerXFill:upperXFill, lowerYFill:upperYFill] = 0
    image[lowerXFill:upperXFill, lowerYFill:upperYFill] = newRegion + oldRegion
   
    return mask, image
                

def erase(image, mask, window=(9, 9)):
    mask = (mask / 255).round().astype(np.uint8)
    image_dims = image.shape[:2]
    confidence = (1 - mask).astype(np.float64)
    still_processing = math.inf
    
    while still_processing != 0:
        #lab_image = cv2.cvtColor((image.astype(np.float32) / 256), cv2.COLOR_BGR2LAB)
        
        # Compute the fill front.
        fill_front = compute_fill_front(mask)
        
        # Compute priority for each point in the fill front.
        priority, updated_confidence = compute_priority(image, fill_front, mask, window)
        
        # Identify the point with the highest priority.
        max_priority_idx = np.unravel_index(np.argmax(priority), priority.shape)
        max_y, max_x = max_priority_idx
        
        # Define the region around the point with highest priority.
        half_window = (window[0] // 2, window[1] // 2)
        x1, x2 = max(max_x - half_window[0], 0), min(max_x + half_window[0] + 1, image_dims[1])
        y1, y2 = max(max_y - half_window[1], 0), min(max_y + half_window[1] + 1, image_dims[0])
        
        # Extract the target regions from the image and mask.
        target_image = image[y1:y2, x1:x2]
        #target_image_lab = lab_image[y1:y2, x1:x2]
        target_mask = mask[y1:y2, x1:x2, np.newaxis].repeat(3, axis=2)
        
        # Find the best match to replace the target region.
        source_mask = 1 - target_mask
        best_match_region = find_best_match(image, mask, window, (max_x, max_y))
        
        # Update the confidence map and the image/mask.
        front_points = np.argwhere(target_mask[:, :, 0] == 1)
        confidence[front_points[:, 0] + y1, front_points[:, 1] + x1] = confidence[max_y, max_x]
        image, mask = update_Mask_Image(image, mask, best_match_region, target_image, target_mask, source_mask, [x1, x2, y1, y2])
        
        still_processing = mask.sum()
        print(f"Remaining pixels to paint: {still_processing}")

    return image.astype(np.uint8)


if __name__ == '__main__':

    output_dir = os.path.join(OUT_FOLDER)
    
    try:
        os.makedirs(output_dir)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise
    
    image_name = SOURCE_FOLDER + 'target_01.jpg'
    mask_name = SOURCE_FOLDER + 'mask_01.jpg'

    image = cv2.imread(image_name)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = cv2.imread(mask_name, cv2.IMREAD_GRAYSCALE)

    output = erase(image, mask, window=(22,22))
    cv2.imwrite(OUT_FOLDER + 'result_01.png', output)




