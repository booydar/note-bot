def get_text(ocr_result):
    lines = []
    line = []
    coord = []
    for res in ocr_result:
        s = res[0]
        y_min, y_max = s[0][1], s[-1][1]
        if len(line) == 0:
            coord.append((y_min, y_max))
            line.append(res[1])
        else:
            last_y_min, last_y_max = coord[-1]
            intersection = min(y_max, last_y_max) - max(y_min, last_y_min)
            row_height = max(y_max - y_min, last_y_max - last_y_min)
            if intersection / row_height > 0.5:
                coord.append((y_min, y_max))
                line.append(res[1])
            else:
                lines.append(line)
                coord = [(y_min, y_max)]
                line = [res[1]]
    text = '\n'.join([' '.join(l) for l in lines])
    return text

def get_text_on_image(reader, img_path, min_line_len=0, min_confidence=0.4):
    result = reader.readtext(img_path)
    result = [r for r in result if len(r[1]) > min_line_len and r[2] > min_confidence]
    return get_text(result)