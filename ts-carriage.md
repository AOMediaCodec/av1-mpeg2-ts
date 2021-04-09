# AV1 specification for carriage inside MPEG-TS

**NOTA BENE: this is a work-in-progress specification**

Copyright 2021, The Alliance for Open Media

Licensing information is available at http://aomedia.org/license/

The MATERIALS ARE PROVIDED “AS IS.” The Alliance for Open Media, its members, and its contributors expressly disclaim any warranties (express, implied, or otherwise), including implied warranties of merchantability, non-infringement, fitness for a particular purpose, or title, related to the materials. The entire risk as to implementing or otherwise using the materials is assumed by the implementer and user. IN NO EVENT WILL THE ALLIANCE FOR OPEN MEDIA, ITS MEMBERS, OR CONTRIBUTORS BE LIABLE TO ANY OTHER PARTY FOR LOST PROFITS OR ANY FORM OF INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES OF ANY CHARACTER FROM ANY CAUSES OF ACTION OF ANY KIND WITH RESPECT TO THIS DELIVERABLE OR ITS GOVERNING AGREEMENT, WHETHER BASED ON BREACH OF CONTRACT, TORT (INCLUDING NEGLIGENCE), OR OTHERWISE, AND WHETHER OR NOT THE OTHER MEMBER HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## 1. Introduction

This specification provides implementation guidelines on how to multiplex the AV1 codec inside the MPEG-TS format.
It defines the carriage of AV1 in a single PID, assuming buffer model info from the first operating point. It may not be optimal for layered streams or streams with multiple operating points. Future versions may incorporate this capability.

This document relies on understanding the AV1 specification and the TS specifications.

### Modal verbs terminology
In the present document "shall", "shall not", "should", "should not", "may", "need not", "will", "will not", "can" and "cannot" are to be interpreted as described in clause 3.2 of the ETSI Drafting Rules (Verbal forms for the expression of provisions).

## 2. References

### 2.1 Normative references

Referenced normative documents:

* AV1 specification, as hosted on the [AOM website](https://aomedia.org/av1-bitstream-and-decoding-process-specification/), also known as "the AV1 Bitstream & Decoding Process Specification".
* MPEG-TS specification, **ISO/IEC 13818-1:2018**
* Digital Video Broadcasting (DVB); Specification for Service Information (SI) in DVB systems, **ETSI EN 300 468**

### 2.2 Informative references

So far, none.

### 2.3 Definitions

 * **AV1**: the 1.0.0 version of the AV1 codec produced by Alliance of Open Media, as defined in the AV1 Bitstream & Decoding Process Specicitation.

 * **AV1 access unit**: a Decodable Frame Group as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

## 3. Generic Identification of AV1 streams

The *format_identifier*, as used in the Registration Descriptor is

'AV1 ' *A-V-1-space*

## 4. Descriptor
> Need to register format_identifier (SMPTE) *and* EN 300 468 Private data specifier descriptor
 https://smpte-ra.org/mpeg-ts-ids.

The presence of a Registration Descriptor is mandatory and shall be the first in the PMT loop and included before an AV1 video descriptor

### 4.1 AV1 video descriptor

> Need to use DVB private data specifier descriptor beforehands, with a private data specifier registered from https://www.dvbservices.com/identifiers/private_data_spec_id.
> Requested 07-12-2018

The AV1 video descriptor is based on a "Private data specifier descriptor" in ETSI EN 300 468.

For an AV1 video stream, the AV1 video descriptor provides basic information for identifying coding parameters, such as profile and level parameters of that AV1 video stream. The same data structure as **AV1CodecConfigurationRecord** in ISOBMFF is used to aid conversion between the two formats.


| Syntax                           | No. Of bits | Mnemonic   |
|:---------------------------------|:-----------:|:----------:|
| AV1_descriptor() {               |             |            |
|       **descriptor_tag**         | **8**       | **uimsbf** |
|       **descriptor_length**      | **8**       | **uimsbf** |
|       **private_data_specifier** | **32**      | **uimsbf** |
|       **marker**                 | **1**       | **bslbf**  |
|       **version**                | **7**       | **uimsbf** |
|       **seq_profile**            | **3**       | **uimsbf** |
|       **seq_level_idx_0**        | **5**       | **uimsbf** |
|       **seq_tier_0**             | **1**       | **bslbf**  |
|       **high_bitdepth**          | **1**       | **bslbf**  |
|       **twelve_bit**             | **1**       | **bslbf**  |
|       **monochrome**             | **1**       | **bslbf**  |
|       **chroma_subsampling_x**   | **1**       | **bslbf**  |
|       **chroma_subsampling_y**   | **1**       | **bslbf**  |
|       **chroma_sample_position** | **2**       | **uimsbf** |
|       **hdr_wcg_idc**            | **2**       | **uimsbf** |
|       **reserved_zeros**         | **1**       | **bslbf** |
|       **initial_presentation_delay_present**  | **1**      | **bslbf** |
|       if (initial_presentation_delay_present) {            |
|       **initial_presentation_delay_minus_one** |  **4**  | **uimsbf**  |
|       } else {                   |             |            |
|       **reserved_zeros**         | **4**       | **uimsbf** |
|       }                          |             |            |
| }                                |             |            |

### 4.2 Semantic definition of fields in AV1 video descriptor

**descriptor_tag** - This value shall be set to 0x5F.

**private_data_specifier** - This value shall be set to FIXME.

**marker** - This value shall be set to 1.

**version** - This field indicates the version of the AV1_Descriptor. This value shall be set to 1.

**seq_profile**, **seq_level_idx_0** and **high_bitdepth** - These fields shall be coded according to the semantics defined in AV1 Bitstream and Decoding Process Specification.

**seq_tier_0**, **twelve_bit**, **monochrome**, **chroma_subsampling_x**, **chroma_subsampling_y**, **chroma_sample_position** - These fields shall be coded according to the same semantics when they are present. If they are not present, they will be coded using the value inferred by the semantics.

**hdr_wcg_idc** - The value of this syntax element indicates the presence or absence of high dynamic range (HDR) and/or wide color gamut (WCG) video components in the associated PID according to Table 2-112. HDR is defined to be video that has high dynamic range if the video stream EOTF is higher than the Rec. ITU-R BT.1886 reference EOTF. WCG is defined to be video that is coded using colour primaries with a colour gamut not contained within Rec. ITU-R BT.709.

| **hdr_wcg_idc** | **Description** |
|:---------------:|:----------------|
| 0               | SDR, i.e., video is based on the Rec. ITU-R BT.1886 reference EOTF with a color gamut that is contained within Rec. ITU-R BT.709 with a Rec. ITU-R BT.709 container |
| 1               | WCG only, i.e., video color gamut in a Rec ITU-R BT.2020 container that exceeds Rec. ITU-R BT.709  |
| 2               | Both HDR and WCG are to be indicated in the stream |
| 3               | No indication made regarding HDR/WCG or SDR characteristics of the stream  |

**reserved_zeros** - Will be set to ones.

**initial_presentation_delay_present** - Indicates **initial_presentation_delay_minus_one** field is present.

**initial_presentation_delay_minus_one** - Ignored for MPEG-TS use, included only to aid conversion to/from ISOBMFF.

## 5 Carriage of AV1

### 5.1 Constraints for the transport of AV1

For AV1 video streams, the following constraints additionally apply:
 * An AV1 video stream conforming to a profile defined in Annex A of AV1 Bitstream & Decoding Process Specification shall be an element of a Rec. ITU-T H.222.0 | ISO/IEC 13818-1 program and the stream_type for this elementary stream shall be equal to 0x06 (Rec. ITU-T H.222.0 | ISO/IEC 13818-1 PES packets containing private data).
 * An AV1 video stream shall have the low overhead byte stream format as defined in AV1 Bitstream & Decoding Process Specification.
 * An AV1 bitstream is composed of a sequence of OBUs, grouped into Decodable Frame Groups.
 * The sequence_header_obu as specified in AV1 Bitstream & Decoding Process Specification, that are necessary for decoding an AV1 video stream shall be present within the elementary stream carrying that AV1 video stream.
 * An OBU shall contain the *obu_size* field.
 * OBU trailing bits should be limited to byte alignment and should not be used for padding.
 * Tile List OBUs shall not be used
 * Temporal Delimiters may be removed
 * Redundant Frame Headers and Padding OBUs may be used.

### 5.2 Carriage in PES packets

AV1 Bitstream & Decoding Process Specification video is carried in PES packets as PES_packet_data_bytes, using the stream_id 0xBD (private_stream_id_1).

The highest level that may occur in an AV1 video stream, as well as a profile and tier that the entire stream conforms to, shall be signalled using the AV1 video descriptor.

If an AV1 video descriptor is associated with an AV1 video stream, then this descriptor shall be conveyed in the descriptor loop for the respective elementary stream entry in the program map table.
This specification does not specify the presentation of AV1 Bitstream & Decoding Process Specification streams in the context of a program stream.

For PES packetization, no specific data alignment constraints apply, except when random_access_indicator is set to 1. When it is set, a PES_packet shall start, and in its header, data_alignment_indicator shall be set to 1. When error resilience is a consideration, it is recommended to set one, and only one, AV1 access unit per PES, and that all PES have data_alignment_indicator set to 1. Usage of *data_stream_alignment_descriptor* is not specified and the only allowed *alignment_type* is 1 (Access unit level). Future versions of this specification may define other values.

For synchronization and STD management, PTSs and, when appropriate, DTSs are encoded in the header of the PES packet that carries the AV1 Bitstream & Decoding Process Specification video elementary stream data. For PTS and DTS encoding, the constraints and semantics apply as defined in the PES Header and associated constraints on timestamp intervals.

### 5.3 Buffer Pool management

Carriage of an AV1 video stream over Rec. ITU-T H.222.0 | ISO/IEC 13818-1 does not impact the size of the Buffer Pool.

For decoding of an AV1 video stream in the STD, the size of the Buffer Pool is as defined in AV1 Bitstream & Decoding Process Specification. The Buffer Pool shall be managed as specified in Annex E of AV1 Bitstream & Decoding Process Specification.

A decoded AV1 access unit enters the Buffer Pool instantaneously upon decoding the AV1 access unit, hence at the Scheduled Removal Timing of the AV1 access unit. A decoded AV1 access unit is presented at the Presentation Time.

If the AV1 video stream provides insufficient information to determine the Scheduled Removal Timing and the Presentation Time of AV1 access units, then these time instants shall be determined in the STD model from PTS and DTS timestamps as follows:
 1. The Scheduled Removal Timing of AV1 access unit n is the instant in time indicated by DTS(n) where DTS(n) is the DTS value of AV1 access unit n.
 2. The Presentation Time of AV1 access unit n is the instant in time indicated by PTS(n) where PTS(n) is the PTS value of AV1 access unit n.

### 5.4 T-STD Extensions for AV1

When there is an AV1 video stream in an Rec. ITU-T H.222.0 | ISO/IEC 13818-1 program, the T-STD model as described in the section "Transport stream system target decoder" is extended as illustrated in figure X-YY and as specified below.

> TODO : Diagram similar to T-REC-H.222.0-201703-S!!PDF-E.pdf 2.17.2

#### TB<sub>n</sub>, MB<sub>n</sub>, EB<sub>n</sub> buffer management

The following additional notations are used to describe the T-STD extensions and are illustrated in Figure X-YY.

| Notation | Definition |
|:--|:--|
| t(i) | indicates the time in seconds at which the i-th byte of the transport stream enters the system target decoder |
| TB<sub>n</sub> | is the transport buffer for elementary stream n |
| TBS | is the size of the transport buffer TBn, measured in bytes |
| MB<sub>n</sub> | is the multiplexing buffer for elementary stream n |
| MBS<sub>n</sub> | is the size of the multiplexing buffer MBn, measured in bytes |
| EB<sub>n</sub> | is the elementary stream buffer for the AV1 video stream |
| EBS<sub>n</sub> | is the size of the multiplexing buffer MBn, measured in bytes |
| j | is an index to the AV1 access unit of the AV1 video stream |
| A<sub>n</sub>(j) | is the j-th access unit of the AV1 video bitstream |
| td<sub>n</sub> (j) | is the decoding time of An(j), measured in seconds, in the system target decoder |
| Rx<sub>n</sub> | is the transfer rate from the transport buffer TBn to the multiplex buffer MBn as specified below. |
| Rbx<sub>n</sub> | is the transfer rate from the multiplex buffer MBn to the elementary stream buffer EBn as specified below |

The following apply:
 * There is exactly one transport buffer TB<sub>n</sub> for the received AV1 video stream where the size TBS is fixed to 512 bytes.
 * There is exactly one multiplexing buffer MB<sub>n</sub> for the AV1 video stream, where the size MBS<sub>n</sub> of the multiplexing buffer MB is constrained as follows:
 MBS<sub>n</sub> = BS<sub>mux</sub> + BS<sub>oh</sub> + 0.1 x BufferSize
where BS<sub>oh</sub>, packet overhead buffering, is defined as:
BS<sub>oh</sub> = (1/750) seconds × max{ 1100 × BitRate, 2 000 000 bit/s}
and BS<sub>mux</sub>, additional mutliplex buffering, is defined as:
BS<sub>mux</sub> = 0.004 seconds ×max{ 1100 × BitRate, 2 000 000 bit/s}
BufferSize and BitRate are defined in Annex E of the AV1 Bitstream & Decoding Process Specification
 * There is exactly one elementary stream buffer EB<sub>n</sub> for all the elementary streams in the set of received elementary streams associated by hierarchy descriptors, with a total size EBS<sub>n</sub>:
EBS<sub>n</sub> = BufferSize
 * Transfer from TB<sub>n</sub> to MB<sub>n</sub> is applied as follows:
When there is no data in TB<sub>n</sub> then Rx<sub>n</sub> is equal to zero. Otherwise:
Rx<sub>n</sub> = 1.1 x BitRate
 * The leak method shall be used to transfer data from MB<sub>n</sub> to EB<sub>n</sub> as follows:
Rbx<sub>n</sub> = 1.1 × BitRate

If there is PES packet payload data in MB<sub>n</sub>, and buffer EB<sub>n</sub> is not full, the PES packet payload is transferred from MB<sub>n</sub> to EB<sub>n</sub> at a rate equal to Rbx<sub>n</sub>. If EB<sub>n</sub> is full, data are not removed from MB<sub>n</sub>. When a byte of data is transferred from MB<sub>n</sub> to EB<sub>n</sub>, all PES packet header bytes that are in MB<sub>n</sub> and precede that byte are instantaneously removed and discarded. When there is no PES packet payload data present in MB<sub>n</sub>, no data is removed from MB<sub>n</sub>. All data that enters MB<sub>n</sub> leaves it. All PES packet payload data bytes enter EB<sub>n</sub> instantaneously upon leaving MB<sub>n</sub>.

### 5.5 STD delay

The STD delay of any AV1 video through the system target decoders buffers TB<sub>n</sub>, MB<sub>n</sub>, and EB<sub>n</sub> shall be constrained by td<sub>n</sub>(j) – t(i) ≤ 10 seconds for all j, and all bytes i in access unit A<sub>n</sub>(j).

### 5.6 Buffer management conditions

Transport streams shall be constructed so that the following conditions for buffer management are satisfied:
* Each TB<sub>n</sub> shall not overflow and shall be empty at least once every second.
* Each MB<sub>n</sub>, EB<sub>n</sub> and Buffer Pool shall not overflow.
* EB<sub>n</sub> shall not underflow, except when the Operating parameters info syntax has low_delay_mode_flag set to '1'. Underflow of EB<sub>n</sub> occurs for AV1 access unit A<sub>n</sub>(j) when one or more bytes of A<sub>n</sub>(j) are not present in EB<sub>n</sub> at the decoding time td<sub>n</sub>(j).

## 6 Definition of DTS and PTS

An AV1 stream multiplexed into MPEG-TS may contain *decoder_model_info* syntax elements but this is not mandatory.

### 6.1 PTS

If a PTS is present in the PES packet header, it shall refer to the first AV1 access unit that commences in this PES packet.
If a PTS is not present in the PES packet header, it may be possible to compute its value based on the presence of timing information in the bitstream or by other means (e.g by using *equal_picture_interval*).

The PTS for a Decodable Frame Group (DFG) containing a frame with *show_frame* = 1 is the PTS of that frame.
The PTS for a DFG with only *show_frame* = 0 is:

* If the frame is referenced by a *show_existing_frame*, use the PTS of the first TU with the corresponding *show_existing_frame*
* If the frame is never referenced (*showable_frame* = 0), use any PTS value, it is recommended to use a PTS equal to the DTS of the frame

To achieve consistency between the STD model and the buffer model defined in Annex E of the AV1 Bitstream & Decoding Process Specification, for each AV1 access unit the PTS value in the STD shall, within the accuracy of their respective clocks, indicate the same instant in time as the PresentationTime in the decoder buffer model, as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

### 6.2 DTS

If a DTS is present in the PES packet header, it shall refer to the first AV1 access unit that commences in this PES packet.

To achieve consistency between the STD model and the buffer model defined in Annex E of the AV1 Bitstream & Decoding Process Specification, for each AV1 access unit the DTS value in the STD shall, within the accuracy of their respective clocks, indicate the same instant in time as the ScheduledRemovalTiming in the decoder buffer model, as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

## 7. Acknowledgements

This Technical Specification has been produced by VideoLAN, with inputs from the authors mentioned below who are from the following companies: ATEME, OpenHeadend, Open Broadcast Systems, Videolabs under the direction of VideoLAN.

## Authors
- Jean Baptiste Kempf (jb@videolan.org)
- Kieran Kunhya (kierank@obe.tv)
- Adrien Maglo (adrien@videolabs.io)
- Christophe Massiot (cmassiot@openheadend.tv)
- Mathieu Monnier (m.monnier@ateme.com)
- Mickael Raulet (m.raulet@ateme.com)
