/*
 * Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

contextImageTimeout = null;

const vars = $('meta[name="django-vars"]');
imageId = `main-${vars.attr('image-id')}`;
imageSrc = vars.attr('main-img-src');

// Show the context image in place of the original
function displayContextImage(contextImage) {
    var mainImage = document.getElementById(imageId);
    mainImage.src = contextImage.src;
    $(".a9s-annotationlayer").hide();

    if (contextImageTimeout) {
        clearTimeout(contextImageTimeout);
    }
}


// Change the displayed image back to the original image being annotated
function revertContextImage() {
    var mainImage = document.getElementById(imageId);

    // Delay switching images to avoid flickering
    contextImageTimeout = setTimeout(function () {
        let anyImgHovered = false;

        $('#context-image-container').find('img').each(function() {
            if ($(this).is(':hover')) {
                anyImgHovered = true;
                return false;
            }
        });

        // Don't switch image if still hovering context
        if (!anyImgHovered) {
            mainImage.src = imageSrc;
            $(".a9s-annotationlayer").show();
        }
    }, 1000)
}
